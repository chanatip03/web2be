"""Health and system status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.deployment.services.docker.client import docker_client
from app.deployment.services.deployer.pipeline import project_store, deployment_store

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """System health check."""
    docker_ok = docker_client.is_available()
    return {
        "status": "healthy" if docker_ok else "degraded",
        "docker_available": docker_ok,
        "projects_count": len(project_store.list_all()),
        "deployments_count": len(deployment_store.list_all()),
    }


@router.get("/api/system/status")
async def system_status():
    """Detailed system status."""
    projects = project_store.list_all()
    deployments = deployment_store.list_all()

    active = [d for d in deployments if d.status in ("success", "running")]

    return {
        "docker_available": docker_client.is_available(),
        "total_projects": len(projects),
        "total_deployments": len(deployments),
        "active_deployments": len(active),
        "deployment_by_status": {
            status: len([d for d in deployments if d.status == status])
            for status in set(d.status for d in deployments)
        } if deployments else {},
    }
