"""Submission Bundle Preview API.

Pulls a .tar.gz bundle from Cloudflare R2, runs it as Docker containers,
and serves the deployed web app through the existing preview proxy.

Endpoints match the pattern the frontend page.tsx already calls:
    POST   /api/project/{submission_id}/preview/start   — launch / re-use
    GET    /api/project/{submission_id}/preview/status  — poll status
    DELETE /api/project/{submission_id}/preview/stop    — manual teardown
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.deployment.core.config import settings
from app.deployment.services.docker.bundle_runner import run_from_bundle
from app.deployment.services.docker.client import docker_client
from app.deployment.services.deployer.pipeline import deployment_store
from app.deployment.models.deployment import DeploymentStatus, ServicePortMapping
from app.utils.r2 import get_file_bytes, R2_PUBLIC_URL
from app.db.database import SessionLocal
from app.models.schema import Project as DBProject

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project", tags=["Submission Preview"])

# ── Preview TTL ──────────────────────────────────────────────────────────────
_TTL_SECONDS = settings.preview_ttl_seconds  # used only for expires_at display

# ── In-memory session store ───────────────────────────────────────────────────
# Keyed by submission_id.  Persisted only for the process lifetime so a server
# restart will trigger a fresh deploy on next visit (which is acceptable).
_sessions: Dict[str, "PreviewSession"] = {}


class PreviewSession(BaseModel):
    submission_id: str
    display_id: str = ""           # Original ID used for display (e.g. numeric project ID)
    status: str = "starting"       # starting | running | error | stopped
    preview_url: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS)
    )
    compose_project: str = ""
    runtime_dir: str = ""
    bundle_path: str = ""
    loaded_images: List[str] = Field(default_factory=list)
    service_ports: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def seconds_remaining(self) -> int:
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))


def _resolve_submission_id(id_or_uuid: str) -> str:
    """Resolve a project ID (numeric) or submission UUID to a submission UUID."""
    if id_or_uuid.isdigit():
        # 1. Try Database lookup
        try:
            with SessionLocal() as db:
                proj = db.query(DBProject).filter(DBProject.id == int(id_or_uuid)).first()
                if proj and proj.submission_uuid:
                    return proj.submission_uuid
        except Exception as e:
            logger.warning("Failed to resolve project ID %s from DB: %s", id_or_uuid, e)

        # 2. Fallback: Search manifests on disk (useful for older records or DB sync issues)
        try:
            import json
            submissions_dir = Path(settings.submissions_dir)
            if submissions_dir.exists():
                for manifest_path in submissions_dir.glob("*/manifest.json"):
                    try:
                        with open(manifest_path, "r") as f:
                            data = json.load(f)
                            if str(data.get("project_db_id")) == id_or_uuid:
                                logger.info("Resolved project ID %s to UUID %s from disk manifest", id_or_uuid, manifest_path.parent.name)
                                return manifest_path.parent.name
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Failed to resolve project ID %s from disk manifests: %s", id_or_uuid, e)

    return id_or_uuid


# ── Helpers ───────────────────────────────────────────────────────────────────

def _runtime_dir(submission_id: str) -> Path:
    base = Path(settings.data_dir) / "previews"
    base.mkdir(parents=True, exist_ok=True)
    return base / submission_id


def _compose_project(submission_id: str) -> str:
    """Deterministic compose project name (max 63 chars, lowercase, no dashes at start)."""
    return submission_id


def _r2_bundle_key(submission_id: str) -> str:
    return f"submissions/{submission_id}/bundle.tar.gz"


def _download_bundle(submission_id: str, target_path: Path) -> None:
    """Download .tar.gz bundle from R2 to target_path."""
    key = _r2_bundle_key(submission_id)
    logger.info("Downloading bundle from R2: %s", key)
    from app.utils.r2 import download_file_to_disk
    download_file_to_disk(key, str(target_path))
    logger.info("Bundle downloaded to %s", target_path)


def _teardown(submission_id: str) -> None:
    """Stop compose services and remove runtime artifacts and loaded images."""
    session = _sessions.get(submission_id)
    if not session:
        return

    runtime = Path(session.runtime_dir)
    bundle_path = Path(session.bundle_path) if session.bundle_path else None
    project = session.compose_project

    logger.info("Tearing down preview for %s (compose_project=%s)", submission_id, project)
    try:
        from app.deployment.services.docker.client import docker_client
        if runtime.exists():
            docker_client.compose_down(str(runtime), project, remove_volumes=True)
            
        # Fallback manual cleanup in case compose_down fails or misses some containers
        try:
            containers = docker_client.client.containers.list(
                all=True, filters={"label": f"com.docker.compose.project={project}"}
            )
            for c in containers:
                try:
                    c.remove(force=True)
                except Exception as e:
                    logger.warning("Failed to force remove container %s: %s", c.name, e)
        except Exception as e:
            logger.warning("Failed to list containers for fallback cleanup: %s", e)
            
    except Exception as exc:
        logger.warning("compose_down failed for %s: %s", submission_id, exc)

    try:
        if runtime.exists():
            shutil.rmtree(runtime, ignore_errors=True)
    except Exception as exc:
        logger.warning("rmtree failed for %s: %s", submission_id, exc)

    try:
        if bundle_path and bundle_path.exists():
            bundle_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("bundle cleanup failed for %s: %s", submission_id, exc)

    if session.loaded_images:
        docker_client.remove_images(session.loaded_images)

    session.status = "stopped"
    session.preview_url = None
    _sessions[submission_id] = session

    dep = deployment_store.get(submission_id)
    if dep:
        dep.status = "stopped"
        dep.preview_url = None
        deployment_store.save(dep)


def _schedule_cleanup(submission_id: str) -> None:
    """Schedule a 5-minute auto-stop timer via the shared submission cleanup helper.

    Delegates to ``_schedule_submission_cleanup`` in submission/service.py so
    that the preview activation and the submission pipeline share the same timer
    mechanism, cleanup logic, and configurable delay.
    """
    try:
        from app.core.submission.service import _schedule_submission_cleanup
        _schedule_submission_cleanup(submission_id)
    except Exception as exc:
        logger.warning("Failed to schedule auto-stop for preview %s: %s", submission_id, exc)


def _launch_bundle(submission_id: str) -> PreviewSession:
    """Download bundle + docker load + compose up.  Returns updated session."""
    session = _sessions[submission_id]
    runtime = _runtime_dir(submission_id)
    # Prevent bundle deletion by extract_bundle(..., overwrite=True) which wipes runtime_dir
    bundle_path = runtime.parent / f"{submission_id}_bundle.tar.gz"

    try:
        # 1. Download from R2
        _download_bundle(submission_id, bundle_path)
        session.bundle_path = str(bundle_path)

        # 2. run_from_bundle: extract → docker load → compose up
        compose_project = _compose_project(submission_id)
        result = run_from_bundle(
            bundle_path=bundle_path,
            runtime_dir=runtime,
            compose_project=compose_project,
            remove_existing=True,
        )

        # 3. Update session
        session.status = "running"
        service_ports_data = result.get("service_ports", [])

        # Build direct container URL from service_ports (prefer frontend port)
        direct_url = None
        for sp in service_ports_data:
            if not isinstance(sp, dict):
                continue
            host_port = sp.get("host_port") or sp.get("hostPort")
            if host_port:
                from urllib.parse import urlparse as _urlparse
                base = (settings.public_base_url or "http://localhost").rstrip("/")
                _p = _urlparse(base)
                # If using HTTPS (like ngrok), direct ports won't work, so we rely on proxy.
                if _p.scheme == "https" or "ngrok" in _p.hostname:
                    continue
                    
                candidate = f"{_p.scheme}://{_p.hostname}:{host_port}"
                if sp.get("service") == "frontend":
                    direct_url = candidate
                    break
                if direct_url is None:
                    direct_url = candidate  # use first available as fallback

        # Last resort: proxy URL
        display_id = session.display_id or submission_id
        session.preview_url = direct_url or f"/preview/{display_id}/"
        session.compose_project = compose_project
        session.runtime_dir = str(runtime)
        session.loaded_images = result.get("image_refs", [])
        session.service_ports = service_ports_data

        logger.info(
            "Preview started for %s → %s (project=%s)",
            submission_id, session.preview_url, compose_project,
        )


    except Exception as exc:
        logger.exception("Failed to launch bundle preview for %s: %s", submission_id, exc)
        session.status = "error"
        session.error = str(exc)

    _sessions[submission_id] = session

    # 4. Sync with global deployment_store so the preview proxy (preview.py) routes correctly
    dep = deployment_store.get(submission_id)
    if not dep:
        dep = DeploymentStatus(
            deployment_id=submission_id,
            project_id=submission_id,
        )
    dep.status = session.status
    dep.preview_url = session.preview_url
    dep.compose_project = session.compose_project
    if session.status == "running":
        valid_ports = [sp for sp in (session.service_ports or []) if isinstance(sp, dict)]
        dep.service_ports = [ServicePortMapping(**sp) for sp in valid_ports] if valid_ports else None
        dep.compose_services = [sp.get("service") for sp in valid_ports if sp.get("service")] if valid_ports else None
        # Default to fullstack to ensure frontend/backend proxying handles edge cases
        if not dep.deploy_mode or dep.deploy_mode == "auto":
            dep.deploy_mode = "fullstack"
    deployment_store.save(dep)

    return session


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/{submission_id}/preview/start")
async def start_preview(submission_id: str, background_tasks: BackgroundTasks, request: Request):
    """Pull the submission bundle from R2 and run it as Docker containers.

    - If already running: returns immediately with current URL.
    - If starting: returns status='starting'; poll /status.
    - If stopped or error: re-launches.
    - Container auto-stops after the configured preview TTL.
    """
    original_id = submission_id
    submission_id = _resolve_submission_id(submission_id)
    existing = _sessions.get(submission_id)

    # Already running — return fast
    if existing and existing.status == "running" and existing.seconds_remaining > 0:
        # Verify containers actually exist
        is_running = False
        try:
            from app.deployment.services.docker.client import docker_client
            containers = docker_client.client.containers.list(
                filters={"label": f"com.docker.compose.project={existing.compose_project}"}
            )
            is_running = any(c.status == "running" for c in containers)
        except Exception:
            pass

        if is_running:
            preview_url = existing.preview_url
            if preview_url and not preview_url.startswith("http"):
                preview_url = f"{str(request.base_url).rstrip('/')}{preview_url}"
                
            return {
                "status": "running",
                "preview_url": preview_url,
                "expires_at": existing.expires_at.isoformat(),
                "seconds_remaining": existing.seconds_remaining,
                "service_ports": existing.service_ports,
            }
        else:
            logger.info("Containers for %s stopped unexpectedly, forcing restart", submission_id)
            existing.status = "stopped"
            _sessions[submission_id] = existing
        if preview_url and not preview_url.startswith("http"):
            preview_url = f"{str(request.base_url).rstrip('/')}{preview_url}"
            
        return {
            "status": "running",
            "preview_url": preview_url,
            "expires_at": existing.expires_at.isoformat(),
            "seconds_remaining": existing.seconds_remaining,
            "service_ports": existing.service_ports,
        }

    # Already starting (launched in a previous call, still booting)
    if existing and existing.status == "starting":
        return {
            "status": "starting",
            "preview_url": None,
            "expires_at": existing.expires_at.isoformat(),
            "seconds_remaining": existing.seconds_remaining,
        }

    # Create / reset session
    session = PreviewSession(
        submission_id=submission_id,
        display_id=original_id,
        compose_project=_compose_project(submission_id),
        runtime_dir=str(_runtime_dir(submission_id)),
    )
    _sessions[submission_id] = session

    # Launch in background so the HTTP response is instant
    background_tasks.add_task(_launch_and_schedule, submission_id)

    return {
        "status": "starting",
        "preview_url": None,
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": session.seconds_remaining,
        "message": "Container is starting. Poll /status for updates.",
    }


def _launch_and_schedule(submission_id: str) -> None:
    """Sync wrapper: launch bundle then schedule TTL cleanup."""
    _launch_bundle(submission_id)
    _schedule_cleanup(submission_id)


@router.get("/{submission_id}/preview/redirect")
async def redirect_to_preview(submission_id: str, request: Request, role: Optional[str] = None, fallback: Optional[str] = None):
    """Redirect to the already-running preview URL without triggering a rebuild."""
    resolved_id = _resolve_submission_id(submission_id)
    
    def _is_container_running(dep) -> bool:
        from app.deployment.services.docker.client import docker_client
        try:
            if dep.container_id:
                return docker_client.get_status(dep.container_id) == "running"
            elif dep.compose_project:
                mappings = docker_client.get_compose_port_mappings(dep.compose_project)
                return len(mappings) > 0
        except Exception:
            pass
        return False
    
    # Check deployment_store to see if it's already deployed
    dep = deployment_store.get(resolved_id)
    if dep and dep.status in {"running", "success"} and dep.preview_url:
        if _is_container_running(dep):
            # Redirect to the proxy URL, not the raw host port
            url = f"/preview/{resolved_id}/"
            if role:
                url += f"?role={role}"
            abs_url = f"{str(request.base_url).rstrip('/')}{url}"
            return RedirectResponse(url=abs_url, status_code=302)
    
    # Check sessions as fallback
    session = _sessions.get(resolved_id)
    if session and session.status == "running" and session.preview_url:
        preview_url = session.preview_url
        if preview_url and not preview_url.startswith("http"):
            preview_url = f"{str(request.base_url).rstrip('/')}{preview_url}"
        return RedirectResponse(url=preview_url, status_code=302)
        
    if fallback:
        return RedirectResponse(url=fallback, status_code=302)
        
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project is not currently deployed or running."
    )


@router.get("/{submission_id}/preview/status")
async def get_preview_status(submission_id: str, request: Request):
    """Poll container status.  Returns preview_url once running."""
    submission_id = _resolve_submission_id(submission_id)
    session = _sessions.get(submission_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active preview session for submission {submission_id}. POST /preview/start first.",
        )

    if session.status == "running":
        # Verify containers actually exist
        is_running = False
        try:
            from app.deployment.services.docker.client import docker_client
            containers = docker_client.client.containers.list(
                filters={"label": f"com.docker.compose.project={session.compose_project}"}
            )
            is_running = any(c.status == "running" for c in containers)
        except Exception:
            pass

        if not is_running:
            logger.info("Containers for %s stopped unexpectedly", submission_id)
            session.status = "stopped"
            session.error = "Container was stopped or deleted."
            _sessions[submission_id] = session

    preview_url = session.preview_url
    if preview_url and not preview_url.startswith("http"):
        preview_url = f"{str(request.base_url).rstrip('/')}{preview_url}"

    return {
        "status": session.status,
        "preview_url": preview_url,
        "error": session.error,
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": session.seconds_remaining,
        "service_ports": session.service_ports,
    }


@router.delete("/{submission_id}/preview/stop", status_code=200)
async def stop_preview(submission_id: str):
    """Manually stop and remove the container before the 2-hour TTL."""
    submission_id = _resolve_submission_id(submission_id)
    if submission_id not in _sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No preview session found for {submission_id}",
        )

    # Cancel any pending auto-stop timer and tear down immediately
    try:
        from app.core.submission.service import _submission_cleanup_timers, _submission_cleanup_timers_lock
        import threading as _t
        with _submission_cleanup_timers_lock:
            existing = _submission_cleanup_timers.pop(submission_id, None)
            if existing is not None:
                existing.cancel()
    except Exception:
        pass

    _teardown(submission_id)

    return {"status": "stopped", "submission_id": submission_id}
