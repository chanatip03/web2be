"""Deployment management API endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.deployment.core.config import settings
from app.deployment.core.exceptions import NotFoundError
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.services.deployer.pipeline import (
    deployment_store,
    project_store,
    run_deployment_sync,
)
from app.deployment.services.docker.client import docker_client

router = APIRouter(prefix="/api", tags=["Deployments"])


def _ensure_backend_env_mount(compose_file_path: str) -> None:
    """Ensure compose backend service has an `.env` file available.

    Some backends (notably Go apps using godotenv) crash if `.env` is missing.
    For compose deployments we mount `./.env.deployer` into `/app/.env`.

    This is a best-effort retrofit for older generated compose files.
    """
    try:
        compose_path = Path(compose_file_path)
        compose_dir = compose_path.parent

        env_path = compose_dir / ".env.deployer"
        if not env_path.exists():
            env_path.write_text("", encoding="utf-8")

        if not compose_path.exists():
            return

        content = compose_path.read_text(encoding="utf-8", errors="replace")
        mount_line = '      - "./.env.deployer:/app/.env:ro"'
        mount_present = mount_line in content

        lines = content.splitlines()
        # Locate the backend service block
        try:
            backend_idx = next(i for i, ln in enumerate(lines) if ln.strip() == "backend:" and ln.startswith("  "))
        except StopIteration:
            return

        def _find_backend_end(current_lines: list[str]) -> int:
            end = len(current_lines)
            for j in range(backend_idx + 1, len(current_lines)):
                if current_lines[j].startswith("  ") and not current_lines[j].startswith("    ") and current_lines[j].strip().endswith(":"):
                    end = j
                    break
            return end

        # Find end of backend service (next top-level service or end)
        end_idx = _find_backend_end(lines)

        # Infer backend container port from the first ports mapping, e.g. "50765:8080".
        backend_container_port: str | None = None
        for i in range(backend_idx + 1, end_idx):
            ln = lines[i].strip()
            if ln.startswith('-') and '"' in ln and ':' in ln:
                # Extract the last colon-separated segment inside quotes.
                try:
                    quoted = ln.split('"', 2)[1]
                    backend_container_port = quoted.split(':')[-1].split('/')[0]
                except Exception:
                    backend_container_port = None
                break

        # If volumes already exist in backend block, just append our mount if missing.
        volumes_idx = None
        for i in range(backend_idx + 1, end_idx):
            if lines[i].strip() == "volumes:" and lines[i].startswith("    "):
                volumes_idx = i
                break

        if not mount_present:
            if volumes_idx is not None:
                insert_at = volumes_idx + 1
                lines.insert(insert_at, mount_line)
            else:
                # Insert volumes after the ports block if present, otherwise near the top.
                insert_at = backend_idx + 1
                ports_idx = None
                for i in range(backend_idx + 1, end_idx):
                    if lines[i].strip() == "ports:" and lines[i].startswith("    "):
                        ports_idx = i
                        break
                if ports_idx is not None:
                    insert_at = ports_idx + 1
                    # After any existing port mappings
                    while insert_at < end_idx and lines[insert_at].lstrip().startswith("-"):
                        insert_at += 1
                lines[insert_at:insert_at] = ["    volumes:", mount_line]

        # Recompute backend end index after insertions.
        end_idx = _find_backend_end(lines)

        # Ensure PORT env matches the container port mapping (if we could infer it).
        if backend_container_port:
            env_idx = None
            for i in range(backend_idx + 1, end_idx):
                if lines[i].strip() == "environment:" and lines[i].startswith("    "):
                    env_idx = i
                    break

            if env_idx is not None:
                has_port = any(
                    ln.startswith("      PORT:") or ln.startswith("      PORT ")
                    for ln in lines[env_idx + 1 : end_idx]
                )
                if not has_port:
                    lines.insert(env_idx + 1, f'      PORT: "{backend_container_port}"')

        compose_path.write_text("\n".join(lines) + ("\n" if content.endswith("\n") else ""), encoding="utf-8")
    except Exception:
        return


def _as_frontend_status(deployment: DeploymentStatus) -> dict:
    return {
        "deploymentId": deployment.deployment_id,
        "projectId": deployment.project_id,
        "projectName": deployment.project_name,
        "status": deployment.status,
        "currentStep": deployment.current_step,
        "previewUrl": deployment.preview_url,
        "errorMessage": deployment.error_message,
        "updatedAt": deployment.updated_at.isoformat() if deployment.updated_at else None,
        "containerId": deployment.container_id,
        "containerState": deployment.container_state,
        "hostPort": deployment.host_port,
        "extraPorts": deployment.extra_ports,
        "imageTag": deployment.image_tag,
    }


def _as_frontend_history(deployment: DeploymentStatus) -> dict:
    status = deployment.status
    if status in {"success", "running"}:
        mapped_status = "running"
    elif status in {"stopped"}:
        mapped_status = "stopped"
    else:
        mapped_status = "failed"

    return {
        "deploymentId": deployment.deployment_id,
        "projectId": deployment.project_id,
        "projectName": deployment.project_name,
        "status": mapped_status,
        "url": deployment.preview_url,
        "lastDeployedAt": deployment.updated_at.isoformat() if deployment.updated_at else None,
        "containerState": deployment.container_state,
        "hostPort": deployment.host_port,
        "extraPorts": deployment.extra_ports,
        "imageTag": deployment.image_tag,
    }


def _logs_text_to_entries(text: str, category: str = "runtime") -> list[dict]:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return []
    entries = []
    for index, line in enumerate(lines):
        entries.append({
            "id": f"{category}-{index + 1}",
            "category": category,
            "level": "error" if "error" in line.lower() else "info",
            "message": line,
        })
    return entries


class DeployRequest(BaseModel):
    deploy_mode: Optional[str] = None
    force_rebuild: bool = False  # frontend-only | backend-only | fullstack | None=auto


# ── Trigger deployment ───────────────────────────────────────────

@router.post("/projects/{project_id}/deploy")
async def deploy_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    body: DeployRequest = DeployRequest(),
    deploy_mode: str | None = Query(None, alias="deploy_mode"),
):
    """Trigger a new deployment.

    deploy_mode: frontend-only | backend-only | fullstack | null (auto).
    force_rebuild: stop existing deployment and rebuild from scratch.
    """
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = deployment_store.get(project_id)
    if existing and (existing.status or "").lower() in {"analyzing", "building", "deploying"}:
        raise HTTPException(
            status_code=409,
            detail=f"Deployment already in progress for project {project_id}",
        )

    # Force rebuild — stop existing deployment for this project first
    if body.force_rebuild:

        for dep in deployment_store.list_all():
            if dep.project_id != project_id:
                continue
            try:
                if dep.compose_project and dep.compose_file_path:
                    compose_dir = str(Path(dep.compose_file_path).parent)
                    docker_client.compose_down(compose_dir, dep.compose_project, remove_volumes=True)
                elif dep.container_id:
                    docker_client.stop_container(dep.container_id)
                    docker_client.remove_container(dep.container_id)
                dep.status = "stopped"
                dep.container_state = "removed"
                deployment_store.save(dep)
            except Exception:
                pass

    # Use a stable deployment id equal to the full project UUID.
    # This keeps project_id/deployment_id aligned and avoids random short ids.
    deployment_id = project_id
    deployment = DeploymentStatus(
        deployment_id=deployment_id,
        project_id=project_id,
        project_name=project.name,
        status="analyzing",
        current_step=1,
        updated_at=datetime.now(),
    )
    deployment_store.save(deployment)

    effective_mode = body.deploy_mode or deploy_mode
    background_tasks.add_task(run_deployment_sync, deployment_id, project_id, effective_mode)

    return {
        "deploymentId": deployment_id,
        "deployment_id": deployment_id,
        "projectId": project_id,
        "project_id": project_id,
        "status": "analyzing",
        "message": "Deployment pipeline started.",
        "deploy_mode": effective_mode or "auto",
        "force_rebuild": body.force_rebuild,
    }


# ── Deployment status ────────────────────────────────────────────

# ── List deployments for a project ────────────────────────────────

@router.get("/projects/{project_id}/deployments")
async def list_project_deployments(project_id: str):
    """List all deployments for a specific project, newest first."""
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    deployments = [
        d for d in deployment_store.list_all() if d.project_id == project_id
    ]
    deployments.sort(
        key=lambda d: d.updated_at or datetime.min, reverse=True
    )
    return [_as_frontend_history(d) for d in deployments]


@router.get("/deployments/{deployment_id}/status")
async def get_deployment_status(deployment_id: str):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return _as_frontend_status(deployment)


# ── Deployment logs ──────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/logs")
async def get_deployment_logs(deployment_id: str, tail: int = 500, filter: str = "all"):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    logs = ""
    try:
        if deployment.compose_project and deployment.compose_file_path:
            # Multi-service: get logs from all compose services
            compose_dir = str(Path(deployment.compose_file_path).parent)
            logs = docker_client.get_compose_logs(
                compose_dir, deployment.compose_project, tail=tail,
            )
        elif deployment.container_id:
            logs = docker_client.get_logs(deployment.container_id, tail=tail)
    except Exception as exc:
        logs = f"Error fetching logs: {exc}"

    category = filter if filter != "all" else "runtime"
    return _logs_text_to_entries(logs, category=category)


# ── Build logs ───────────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/build-logs")
async def get_build_logs(deployment_id: str):
    """Get the Docker image build logs captured during deployment."""
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {
        "deployment_id": deployment_id,
        "build_logs": deployment.build_logs or "",
        "has_logs": bool(deployment.build_logs),
    }


# ── Start / Stop ─────────────────────────────────────────────────

@router.post("/deployments/{deployment_id}/start")
async def start_deployment(deployment_id: str):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Compose deployments: restart via docker compose (no rebuild)
    if deployment.compose_project and deployment.compose_file_path:
        try:
            compose_dir = str(Path(deployment.compose_file_path).parent)

            # Best-effort: ensure older compose files mount `.env.deployer` into `/app/.env`.
            _ensure_backend_env_mount(deployment.compose_file_path)

            # Best-effort: load saved images first (so compose won't need to build)
            project_dir = Path(settings.projects_dir) / deployment.project_id
            saved = docker_client.list_saved_images(str(project_dir))
            for img_info in saved:
                try:
                    docker_client.load_image(img_info["path"])
                except Exception:
                    pass

            docker_client.compose_up(compose_dir, deployment.compose_project, build=False)
            deployment.status = "running"
            deployment.container_state = "running"
            deployment.updated_at = datetime.now()
            deployment_store.save(deployment)
            return _as_frontend_status(deployment)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # If a container was removed, treat it as missing.
    if deployment.container_state == "removed":
        deployment.container_id = None

    # Start an existing container if present
    if deployment.container_id:
        try:
            docker_client.start_container(deployment.container_id)
            deployment.status = "running"
            deployment.container_state = "running"
            deployment.updated_at = datetime.now()
            deployment_store.save(deployment)
            return _as_frontend_status(deployment)
        except Exception:
            # Fall back to restoring from saved images
            deployment.container_id = None

    # Restore from saved images and run a new container
    project_dir = Path(settings.projects_dir) / deployment.project_id
    saved = docker_client.list_saved_images(str(project_dir))
    if not saved:
        raise HTTPException(status_code=400, detail="No container or saved image found")

    loaded_tags: list[str] = []
    for img_info in saved:
        try:
            loaded_tags.append(docker_client.load_image(img_info["path"]))
        except Exception:
            continue

    if not loaded_tags and not deployment.image_tag:
        raise HTTPException(status_code=400, detail="Saved images could not be loaded")

    image_tag = deployment.image_tag or loaded_tags[0]

    # If archives were loaded under a different tag, retag to the deployment's expected tag.
    if deployment.image_tag and loaded_tags and deployment.image_tag != loaded_tags[0]:
        try:
            docker_client.tag_image(loaded_tags[0], deployment.image_tag)
            image_tag = deployment.image_tag
        except Exception:
            # Fall back to running the loaded tag
            image_tag = loaded_tags[0]

    fixed_ports: dict[int, int] | None = None
    if deployment.service_ports:
        # Use the first service port mapping as the primary port
        sp = deployment.service_ports[0]
        fixed_ports = {sp.container_port: sp.host_port}

    try:
        result = docker_client.run_container(
            image_tag,
            name=deployment.project_id,
            fixed_ports=fixed_ports,
        )
        deployment.container_id = result["container_id"]
        deployment.extra_ports = result.get("ports")

        # Refresh preview URL if we know the mapped port
        if result.get("ports"):
            host_port = result["ports"][0].get("hostPort")
            if host_port:
                deployment.host_port = host_port
                deployment.preview_url = f"http://localhost:{host_port}"

        deployment.status = "running"
        deployment.container_state = "running"
        deployment.updated_at = datetime.now()
        deployment_store.save(deployment)
        return _as_frontend_status(deployment)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/deployments/{deployment_id}/stop")
async def stop_deployment(deployment_id: str):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if deployment.container_id:
        docker_client.stop_container(deployment.container_id)
    elif deployment.compose_project and deployment.compose_file_path:
        compose_dir = str(Path(deployment.compose_file_path).parent)
        docker_client.compose_down(compose_dir, deployment.compose_project)

    deployment.status = "stopped"
    deployment.container_state = "stopped"
    deployment.updated_at = datetime.now()
    deployment_store.save(deployment)
    return _as_frontend_status(deployment)

# ── Delete deployment ─────────────────────────────────────────────────

@router.delete("/deployments/{deployment_id}")
async def delete_deployment(deployment_id: str):
    """Stop containers and permanently remove the deployment record."""
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Stop / tear down containers
    try:
        if deployment.compose_project and deployment.compose_file_path:
            compose_dir = str(Path(deployment.compose_file_path).parent)
            docker_client.compose_down(compose_dir, deployment.compose_project)
        elif deployment.container_id:
            docker_client.stop_container(deployment.container_id)
            docker_client.remove_container(deployment.container_id)
    except Exception:
        pass  # Best-effort

    deployment_store.delete(deployment_id)
    return {"message": f"Deployment {deployment_id} deleted"}


# ── Rebuild (redeploy) existing deployment ──────────────────────────────

@router.post("/deployments/{deployment_id}/rebuild")
async def rebuild_deployment(deployment_id: str, background_tasks: BackgroundTasks, body: DeployRequest = DeployRequest()):
    """Stop existing deployment and re-run the full pipeline."""
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    project_id = deployment.project_id
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Tear down current containers
    try:
        if deployment.compose_project and deployment.compose_file_path:
            compose_dir = str(Path(deployment.compose_file_path).parent)
            docker_client.compose_down(compose_dir, deployment.compose_project, remove_volumes=True)
        elif deployment.container_id:
            docker_client.stop_container(deployment.container_id)
            docker_client.remove_container(deployment.container_id)
    except Exception:
        pass

    # Reset deployment state
    deployment.status = "analyzing"
    deployment.current_step = 1
    deployment.error_message = None
    deployment.preview_url = None
    deployment.container_id = None
    deployment.compose_project = None
    deployment.compose_file_path = None
    deployment.service_ports = None
    deployment.updated_at = datetime.now()
    deployment_store.save(deployment)

    background_tasks.add_task(run_deployment_sync, deployment_id, project_id, body.deploy_mode)
    return {
        "deploymentId": deployment_id,
        "status": "analyzing",
        "message": "Rebuild pipeline started.",
    }

# ── Deployment history ───────────────────────────────────────────

@router.get("/deployments/history")
async def deployment_history():
    deployments = deployment_store.list_all()
    return [_as_frontend_history(d) for d in deployments]


# ── Container health ─────────────────────────────────────────────

@router.get("/deployments/{deployment_id}/health")
async def check_deployment_health(deployment_id: str):
    deployment = deployment_store.get(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if not deployment.container_id:
        return {"status": "no_container", "healthy": False}

    status = docker_client.get_status(deployment.container_id)
    return {
        "deployment_id": deployment_id,
        "container_status": status,
        "healthy": status == "running",
        "preview_url": deployment.preview_url,
    }


# ── Image export / import ────────────────────────────────────────

@router.get("/projects/{project_id}/images")
async def list_saved_images(project_id: str):
    """List all saved .tar.gz images for a project."""
    project_dir = Path(settings.projects_dir) / project_id
    images = docker_client.list_saved_images(str(project_dir))
    return {"project_id": project_id, "images": images}


@router.get("/projects/{project_id}/images/{service}/download")
async def download_image(project_id: str, service: str):
    """Download a saved Docker image as .tar.gz."""
    tar_path = Path(settings.projects_dir) / project_id / "images" / f"{service}.tar.gz"
    if not tar_path.exists():
        raise HTTPException(status_code=404, detail=f"No saved image for service '{service}'")

    return FileResponse(
        str(tar_path),
        media_type="application/gzip",
        filename=f"{project_id[:8]}-{service}.tar.gz",
    )


@router.post("/projects/{project_id}/images/restore")
async def restore_from_images(project_id: str, background_tasks: BackgroundTasks):
    """Restore containers from saved .tar.gz images."""
    project_dir = Path(settings.projects_dir) / project_id
    saved = docker_client.list_saved_images(str(project_dir))

    if not saved:
        raise HTTPException(status_code=404, detail="No saved images found")

    loaded_tags = {}
    for img_info in saved:
        try:
            tag = docker_client.load_image(img_info["path"])
            loaded_tags[img_info["service"]] = tag
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to load {img_info['service']}: {exc}")

    return {
        "project_id": project_id,
        "restored_images": loaded_tags,
        "message": f"Loaded {len(loaded_tags)} image(s). Use /deploy to run them.",
    }
