"""Submission Bundle Preview API.

Pulls a .tar.gz bundle from Cloudflare R2, runs it as Docker containers,
and serves the deployed web app through the existing preview proxy.

Endpoints match the pattern the frontend page.tsx already calls:
  POST   /api/project/{submission_id}/preview/start   — launch / re-use
  GET    /api/project/{submission_id}/preview/status  — poll status
  DELETE /api/project/{submission_id}/preview/stop    — manual teardown
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.deployment.core.config import settings
from app.deployment.services.docker.bundle_runner import run_from_bundle
from app.deployment.services.docker.client import docker_client
from app.utils.r2 import get_file_bytes, R2_PUBLIC_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project", tags=["Submission Preview"])

# ── 2-hour TTL ───────────────────────────────────────────────────────────────
_TTL_SECONDS = 2 * 60 * 60   # 2 hours

# ── In-memory session store ───────────────────────────────────────────────────
# Keyed by submission_id.  Persisted only for the process lifetime so a server
# restart will trigger a fresh deploy on next visit (which is acceptable).
_sessions: Dict[str, "PreviewSession"] = {}

# Background cleanup tasks — we keep a reference so they aren't GC'd early.
_cleanup_tasks: Dict[str, asyncio.Task] = {}


class PreviewSession(BaseModel):
    submission_id: str
    status: str = "starting"       # starting | running | error | stopped
    preview_url: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS)
    )
    compose_project: str = ""
    runtime_dir: str = ""
    service_ports: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def seconds_remaining(self) -> int:
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))


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
    data = get_file_bytes(key)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    logger.info("Bundle downloaded: %d bytes → %s", len(data), target_path)


def _teardown(submission_id: str) -> None:
    """Stop compose services and remove runtime directory."""
    session = _sessions.get(submission_id)
    if not session:
        return

    runtime = Path(session.runtime_dir)
    project = session.compose_project

    logger.info("Tearing down preview for %s (compose_project=%s)", submission_id, project)
    try:
        if runtime.exists():
            docker_client.compose_down(str(runtime), project, remove_volumes=True)
    except Exception as exc:
        logger.warning("compose_down failed for %s: %s", submission_id, exc)

    try:
        if runtime.exists():
            shutil.rmtree(runtime, ignore_errors=True)
    except Exception as exc:
        logger.warning("rmtree failed for %s: %s", submission_id, exc)

    session.status = "stopped"
    session.preview_url = None
    _sessions[submission_id] = session


async def _ttl_cleanup(submission_id: str) -> None:
    """Sleep for TTL seconds, then tear down the session."""
    await asyncio.sleep(_TTL_SECONDS)
    logger.info("TTL expired for submission preview %s — stopping container", submission_id)
    _teardown(submission_id)
    _cleanup_tasks.pop(submission_id, None)


def _schedule_cleanup(submission_id: str) -> None:
    """Cancel any existing cleanup task and schedule a fresh one."""
    existing = _cleanup_tasks.pop(submission_id, None)
    if existing and not existing.done():
        existing.cancel()
    try:
        loop = asyncio.get_event_loop()
        task = loop.create_task(_ttl_cleanup(submission_id))
        _cleanup_tasks[submission_id] = task
    except RuntimeError:
        # No running event loop (e.g. during tests) — skip scheduling
        pass


def _launch_bundle(submission_id: str) -> PreviewSession:
    """Download bundle + docker load + compose up.  Returns updated session."""
    session = _sessions[submission_id]
    runtime = _runtime_dir(submission_id)
    # Prevent bundle deletion by extract_bundle(..., overwrite=True) which wipes runtime_dir
    bundle_path = runtime.parent / f"{submission_id}_bundle.tar.gz"

    try:
        # 1. Download from R2
        _download_bundle(submission_id, bundle_path)

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
        session.preview_url = result.get("primary_url")
        session.compose_project = compose_project
        session.runtime_dir = str(runtime)
        session.service_ports = result.get("service_ports", [])

        logger.info(
            "Preview started for %s → %s (project=%s)",
            submission_id, session.preview_url, compose_project,
        )

    except Exception as exc:
        logger.exception("Failed to launch bundle preview for %s: %s", submission_id, exc)
        session.status = "error"
        session.error = str(exc)

    _sessions[submission_id] = session
    return session


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.post("/{submission_id}/preview/start")
async def start_preview(submission_id: str, background_tasks: BackgroundTasks):
    """Pull the submission bundle from R2 and run it as Docker containers.

    - If already running: returns immediately with current URL.
    - If starting: returns status='starting'; poll /status.
    - If stopped or error: re-launches.
    - Container auto-stops after 2 hours.
    """
    existing = _sessions.get(submission_id)

    # Already running — return fast
    if existing and existing.status == "running" and existing.seconds_remaining > 0:
        return {
            "status": "running",
            "preview_url": existing.preview_url,
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


@router.get("/{submission_id}/preview/status")
async def get_preview_status(submission_id: str):
    """Poll container status.  Returns preview_url once running."""
    session = _sessions.get(submission_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active preview session for submission {submission_id}. POST /preview/start first.",
        )

    return {
        "status": session.status,
        "preview_url": session.preview_url,
        "error": session.error,
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": session.seconds_remaining,
        "service_ports": session.service_ports,
    }


@router.delete("/{submission_id}/preview/stop", status_code=200)
async def stop_preview(submission_id: str):
    """Manually stop and remove the container before the 2-hour TTL."""
    if submission_id not in _sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No preview session found for {submission_id}",
        )

    # Cancel scheduled cleanup and tear down immediately
    task = _cleanup_tasks.pop(submission_id, None)
    if task and not task.done():
        task.cancel()

    _teardown(submission_id)

    return {"status": "stopped", "submission_id": submission_id}
