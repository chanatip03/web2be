"""Container state refresh / sync — reconcile deployment records with Docker reality.

On server startup (or on-demand), scan all saved deployment records and check
whether their containers are still running in Docker. Update statuses accordingly.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.deployment.models.deployment import DeploymentStatus, ServicePortMapping
from app.deployment.services.docker.client import docker_client

logger = logging.getLogger(__name__)


def refresh_deployment_state(deployment: DeploymentStatus) -> DeploymentStatus:
    """Check Docker daemon for actual container/compose state and update the deployment record.

    Returns the updated deployment (caller should persist it).
    """
    try:
        if deployment.compose_project:
            return _refresh_compose(deployment)
        elif deployment.container_id:
            return _refresh_single(deployment)
        else:
            # No container info — mark as stopped if was running
            if deployment.status in ("success", "running"):
                deployment.status = "stopped"
                deployment.container_state = "stopped"
            return deployment
    except Exception as exc:
        logger.warning("Failed to refresh state for %s: %s", deployment.deployment_id, exc)
        return deployment


def _refresh_single(deployment: DeploymentStatus) -> DeploymentStatus:
    """Refresh a single-container deployment."""
    try:
        container = docker_client.client.containers.get(deployment.container_id)
        container.reload()
        state = container.status  # "running", "exited", "paused", etc.

        deployment.container_state = state

        if state == "running":
            deployment.status = "running"

            # Re-read port mappings (may change after Docker daemon restart)
            ports_data = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            service_ports = []
            for c_port, bindings in (ports_data or {}).items():
                if bindings:
                    host_port = int(bindings[0]["HostPort"])
                    container_port = int(c_port.split("/")[0])
                    service_ports.append(ServicePortMapping(
                        service="app",
                        container_port=container_port,
                        host_port=host_port,
                        url=f"http://localhost:{host_port}",
                    ))
                    # Update host_port
                    deployment.host_port = host_port

            if service_ports:
                deployment.service_ports = service_ports
                deployment.preview_url = service_ports[0].url

        elif state in ("exited", "dead"):
            deployment.status = "stopped"
        else:
            deployment.container_state = state

    except Exception:
        # Container doesn't exist anymore
        if deployment.status in ("success", "running"):
            deployment.status = "stopped"
            deployment.container_state = "removed"

    return deployment


def _refresh_compose(deployment: DeploymentStatus) -> DeploymentStatus:
    """Refresh a compose-based deployment by scanning for its containers."""
    project_name = deployment.compose_project
    if not project_name:
        return deployment

    try:
        # List containers with compose project label
        containers = docker_client.client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={project_name}"},
        )

        if not containers:
            if deployment.status in ("success", "running"):
                deployment.status = "stopped"
                deployment.container_state = "removed"
            return deployment

        # Check if all are running
        running = []
        stopped = []
        service_ports = []

        for c in containers:
            c.reload()
            # Get service name from label
            labels = c.labels or {}
            svc_name = labels.get("com.docker.compose.service", "unknown")

            if c.status == "running":
                running.append(svc_name)

                # Read port mappings
                ports_data = c.attrs.get("NetworkSettings", {}).get("Ports", {})
                for c_port, bindings in (ports_data or {}).items():
                    if bindings:
                        host_port = int(bindings[0]["HostPort"])
                        container_port = int(c_port.split("/")[0])
                        service_ports.append(ServicePortMapping(
                            service=svc_name,
                            container_port=container_port,
                            host_port=host_port,
                            url=f"http://localhost:{host_port}",
                        ))
            else:
                stopped.append(svc_name)

        if running:
            deployment.status = "running"
            deployment.container_state = "running"
            deployment.compose_services = running + stopped

            if service_ports:
                deployment.service_ports = service_ports
                # Set primary URL (frontend > backend > first available)
                for pref in ("frontend", "backend"):
                    for sp in service_ports:
                        if sp.service == pref:
                            deployment.preview_url = sp.url
                            break
                    if deployment.preview_url:
                        break
                if not deployment.preview_url and service_ports:
                    deployment.preview_url = service_ports[0].url
        else:
            deployment.status = "stopped"
            deployment.container_state = "stopped"

    except Exception as exc:
        logger.warning("Failed to refresh compose state for %s: %s", project_name, exc)

    return deployment


def sync_all_deployments(deployment_store) -> Dict[str, Any]:
    """Scan all deployment records and refresh their Docker state.

    Args:
        deployment_store: The JSON store for deployments.

    Returns:
        Summary of sync results.
    """
    all_deployments = deployment_store.list_all()
    updated = 0
    running = 0
    stopped = 0
    errors = 0

    for dep in all_deployments:
        old_status = dep.status
        try:
            refreshed = refresh_deployment_state(dep)
            if refreshed.status != old_status:
                deployment_store.save(refreshed)
                updated += 1
                logger.info(
                    "Deployment %s: %s → %s",
                    dep.deployment_id, old_status, refreshed.status,
                )

            if refreshed.status in ("running", "success"):
                running += 1
            elif refreshed.status == "stopped":
                stopped += 1
        except Exception as exc:
            errors += 1
            logger.warning("Sync error for %s: %s", dep.deployment_id, exc)

    return {
        "total": len(all_deployments),
        "updated": updated,
        "running": running,
        "stopped": stopped,
        "errors": errors,
    }
