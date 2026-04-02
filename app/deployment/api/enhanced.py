"""Enhanced features API — rollback, secrets, metrics, health, validation, logs."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from app.deployment.core.config import settings
from app.deployment.services.deployer.pipeline import deployment_store, project_store
from app.deployment.services.enhanced.dockerfile_validator import dockerfile_validator
from app.deployment.services.enhanced.health_checker import health_checker
from app.deployment.services.enhanced.metrics_collector import metrics
from app.deployment.services.enhanced.rollback_manager import rollback_manager
from app.deployment.services.enhanced.secrets_manager import secrets_manager
from app.deployment.services.logger import LoggerManager

router = APIRouter(prefix="/api", tags=["Enhanced"])


# ── Rollback ─────────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/versions")
async def list_versions(deployment_id: str):
    return rollback_manager.list_versions(deployment_id)


@router.post("/deployments/{deployment_id}/rollback")
async def rollback(deployment_id: str, body: dict = {}):
    version_id = body.get("version_id")
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if version_id:
        version = rollback_manager.get_version(deployment_id, version_id)
    else:
        version = rollback_manager.get_latest_version(deployment_id)

    if not version:
        raise HTTPException(status_code=404, detail="No version found for rollback")

    return {
        "deployment_id": deployment_id,
        "rolled_back_to": version.get("version_id"),
        "artifacts": list(version.keys()),
    }


# ── Dockerfile validation ────────────────────────────────────────

@router.post("/deployments/{deployment_id}/validate")
async def validate_dockerfile(deployment_id: str):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Find the Dockerfile
    project_dir = Path(settings.projects_dir) / deployment.project_id
    dockerfile_path = project_dir / "Dockerfile"

    if not dockerfile_path.exists():
        raise HTTPException(status_code=404, detail="No Dockerfile found")

    content = dockerfile_path.read_text(encoding="utf-8")
    result = dockerfile_validator.validate(content)
    return result


# ── Secrets ──────────────────────────────────────────────────────

@router.post("/secrets/{deployment_id}")
async def save_secrets(deployment_id: str, body: Dict[str, str]):
    secrets_manager.save(deployment_id, body)
    return {"message": "Secrets saved", "keys": list(body.keys())}


@router.get("/secrets/{deployment_id}")
async def get_secrets(deployment_id: str):
    return secrets_manager.load(deployment_id)


# ── Metrics ──────────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics():
    return metrics.get_metrics()


@router.post("/metrics/reset")
async def reset_metrics():
    metrics.reset()
    return {"message": "Metrics reset"}


# ── Health ───────────────────────────────────────────────────────

@router.get("/health/containers")
async def all_container_health():
    return await health_checker.check_all_containers()


@router.get("/health/containers/{container_id}")
async def container_health(container_id: str):
    return await health_checker.check_container(container_id)


@router.get("/health/http")
async def http_health(url: str):
    return await health_checker.check_http(url)


# ── Project Logs ─────────────────────────────────────────────────

@router.get("/projects/{project_id}/logs")
async def get_project_logs(
    project_id: str,
    channel: str = "general",
    limit: int = 100,
    formatted: bool = False,
):
    """Get log entries for a specific channel.

    - **channel**: general | llm | docker | pipeline | analysis | testing
    - **formatted**: include human-readable ``_text`` field per entry
    """
    log = LoggerManager.get(project_id)
    if formatted:
        entries = log.read_logs_formatted(channel, limit)
    else:
        entries = log.read_logs(channel, limit)
    return {
        "project_id": project_id,
        "channel": channel,
        "count": len(entries),
        "entries": entries,
    }


@router.get("/projects/{project_id}/logs/channels")
async def get_log_channels(project_id: str):
    """List available log channels and their statistics."""
    log = LoggerManager.get(project_id)
    channels = log.get_all_channels()
    return {
        "project_id": project_id,
        "channels": [log.get_channel_stats(ch) for ch in channels],
    }


@router.get("/projects/{project_id}/logs/timeline")
async def get_log_timeline(
    project_id: str,
    limit_per_channel: int = 50,
    deployment_id: Optional[str] = None,
):
    """Get a unified chronological timeline across all log channels.

    Every entry includes: ``_channel``, ``_channel_label``, ``_text``.
    Pass ``deployment_id`` to scope the pipeline channel to a specific deployment.
    """
    log = LoggerManager.get(project_id)
    timeline = log.get_timeline(
        limit_per_channel=limit_per_channel,
        deployment_id=deployment_id,
    )
    return {
        "project_id": project_id,
        "deployment_id": deployment_id,
        "total": len(timeline),
        "entries": timeline,
    }


@router.get("/projects/{project_id}/logs/summary")
async def get_log_summary(project_id: str):
    """Get per-channel statistics and metadata."""
    log = LoggerManager.get(project_id)
    return log.get_summary()


@router.get("/projects/{project_id}/logs/llm")
async def get_llm_logs(project_id: str, limit: int = 50, formatted: bool = True):
    """Get LLM conversation history for a project."""
    log = LoggerManager.get(project_id)
    entries = log.read_logs_formatted("llm", limit) if formatted else log.read_logs("llm", limit)
    return {
        "project_id": project_id,
        "count": len(entries),
        "conversations": entries,
    }


@router.get("/deployments/{deployment_id}/logs/pipeline")
async def get_deployment_pipeline_logs(deployment_id: str, limit: int = 200):
    """Get the pipeline step log for a specific deployment (formatted timeline)."""
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    log = LoggerManager.get(deployment.project_id)
    entries = log.read_logs_formatted("pipeline", limit)
    # Filter to this deployment only
    filtered = [
        e for e in entries
        if not e.get("deployment_id") or e["deployment_id"] == deployment_id
    ]
    return {
        "deployment_id": deployment_id,
        "project_id": deployment.project_id,
        "count": len(filtered),
        "entries": filtered,
    }


# ── Dockerfile / Build Spec viewers ─────────────────────────────

@router.get("/projects/{project_id}/dockerfile")
async def get_dockerfile(project_id: str):
    project_dir = Path(settings.projects_dir) / project_id
    dockerfile_path = project_dir / "Dockerfile"
    if not dockerfile_path.exists():
        raise HTTPException(status_code=404, detail="No Dockerfile found")
    return {
        "project_id": project_id,
        "content": dockerfile_path.read_text(encoding="utf-8"),
    }


@router.get("/projects/{project_id}/build-spec")
async def get_build_spec(project_id: str):
    import json
    project_dir = Path(settings.projects_dir) / project_id
    spec_path = project_dir / "build_spec.json"
    if spec_path.exists():
        return json.loads(spec_path.read_text(encoding="utf-8"))

    # Try from logger
    logger = LoggerManager.get(project_id)
    llm_logs = logger.read_logs("llm", 20)
    for entry in reversed(llm_logs):
        if entry.get("task") == "build_spec" and entry.get("type") == "response":
            return {"source": "logs", "preview": entry.get("response_preview", "")}

    raise HTTPException(status_code=404, detail="No build spec found")
