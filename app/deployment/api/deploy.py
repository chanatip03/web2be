"""Unified deploy API — single endpoint for clone + analyse + deploy.

One call → one ID → everything stored together under that ID.
Supports: GitHub clone, ZIP upload, folder upload.
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional

from app.deployment.core.config import settings
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.models.project import ProjectMetadata
from app.deployment.services.analyzer.file_scanner import build_file_tree
from app.deployment.services.deployer.pipeline import (
    deployment_store,
    project_store,
    run_deployment,
    run_deployment_sync,
)

router = APIRouter(prefix="/api", tags=["Deploy"])


# ── Unified Deploy from GitHub ──────────────────────────────────

class DeployGitHubRequest(BaseModel):
    repo_url: str
    deploy_mode: Optional[str] = None  # frontend-only | backend-only | fullstack | None=auto
    name: Optional[str] = None
    subdir: Optional[str] = None


@router.post("/deploy")
async def unified_deploy(
    background_tasks: BackgroundTasks,
    body: DeployGitHubRequest,
):
    """Clone a repo and deploy in one shot.

    Returns a single `id` used for everything: project, deployment, logs, bundle.
    deploy_mode: frontend-only | backend-only | fullstack | null (auto-detect).
    """
    # One ID for everything
    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    clone_target = project_dir / "_clone"
    project_dir.mkdir(parents=True, exist_ok=True)

    # 1. Clone repo
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", body.repo_url, str(clone_target)],
            capture_output=True,
            text=True,
            timeout=600,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"Git clone failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=408, detail="Git clone timed out (600s)")

    # Use subdir if specified
    effective_root = clone_target / body.subdir if body.subdir else clone_target

    if not clone_target.exists() or not clone_target.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Git clone failed: repository content not found")

    if not effective_root.exists() or not effective_root.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)
        detail = f"Invalid subdir: {body.subdir}" if body.subdir else "Git clone produced no files"
        raise HTTPException(status_code=400, detail=detail)

    # Move to project root level
    for item in effective_root.iterdir():
        if item.name == ".git":
            continue
        dest = project_dir / item.name
        shutil.move(str(item), str(dest))
    shutil.rmtree(clone_target, ignore_errors=True)

    proj_name = body.name or body.repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    # 2. Create project metadata (same ID)
    file_tree_dict = build_file_tree(project_dir)
    from app.deployment.models.project import FileNode
    try:
        file_tree = FileNode.model_validate(file_tree_dict)
    except Exception:
        file_tree = None

    project = ProjectMetadata(
        project_id=project_id,
        name=proj_name,
        project_type="unknown",
        uploaded_at=datetime.now(),
        file_tree=file_tree,
    )
    project_store.save(project)

    # 3. Create deployment record (SAME ID as project)
    deployment = DeploymentStatus(
        deployment_id=project_id,  # ← same as project_id!
        project_id=project_id,
        project_name=proj_name,
        deploy_mode=body.deploy_mode or "auto",
        status="analyzing",
        current_step=1,
        total_steps=5,
        updated_at=datetime.now(),
    )
    deployment_store.save(deployment)

    # 4. Start full pipeline: analyse → build → deploy → bundle
    mode = body.deploy_mode if (body.deploy_mode and body.deploy_mode != "auto") else None
    background_tasks.add_task(
        run_deployment_sync, project_id, project_id, mode,
    )

    return {
        "id": project_id,
        "name": proj_name,
        "deploy_mode": body.deploy_mode or "auto",
        "status": "analyzing",
        "message": "Cloned and deploying. Use this ID for everything.",
    }


# ── Unified Deploy from ZIP ─────────────────────────────────────

@router.post("/deploy/upload")
async def unified_deploy_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(...),
    deploy_mode: str = Form("auto"),
):
    """Upload a ZIP and deploy in one shot. Returns a single `id`."""
    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Extract ZIP
    zip_path = project_dir / "upload.zip"
    contents = await file.read()
    zip_path.write_bytes(contents)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(project_dir)
        zip_path.unlink(missing_ok=True)
    except zipfile.BadZipFile:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Invalid ZIP file")

    # Skip wrapper directories
    project_root = _find_project_root(project_dir)
    if project_root != project_dir:
        for item in project_root.iterdir():
            dest = project_dir / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))

    # Create metadata + deployment (same ID)
    project = ProjectMetadata(
        project_id=project_id,
        name=name,
        project_type="unknown",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)

    mode = deploy_mode if deploy_mode != "auto" else None
    deployment = DeploymentStatus(
        deployment_id=project_id,
        project_id=project_id,
        project_name=name,
        deploy_mode=deploy_mode,
        status="analyzing",
        current_step=1,
        total_steps=5,
        updated_at=datetime.now(),
    )
    deployment_store.save(deployment)

    background_tasks.add_task(run_deployment_sync, project_id, project_id, mode)

    return {
        "id": project_id,
        "name": name,
        "deploy_mode": deploy_mode,
        "status": "analyzing",
        "message": "Uploaded and deploying. Use this ID for everything.",
    }


# ── Unified Deploy from Folder Upload ───────────────────────────

@router.post("/deploy/upload-folder")
async def unified_deploy_folder(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    name: str = Form(...),
    deploy_mode: str = Form("auto"),
):
    """Upload individual files and deploy in one shot. Returns a single `id`."""
    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id

    for upload_file, rel_path in zip(files, paths):
        dest = project_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await upload_file.read()
        dest.write_bytes(content)

    project = ProjectMetadata(
        project_id=project_id,
        name=name,
        project_type="unknown",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)

    mode = deploy_mode if deploy_mode != "auto" else None
    deployment = DeploymentStatus(
        deployment_id=project_id,
        project_id=project_id,
        project_name=name,
        deploy_mode=deploy_mode,
        status="analyzing",
        current_step=1,
        total_steps=5,
        updated_at=datetime.now(),
    )
    deployment_store.save(deployment)

    background_tasks.add_task(run_deployment_sync, project_id, project_id, mode)

    return {
        "id": project_id,
        "name": name,
        "deploy_mode": deploy_mode,
        "status": "analyzing",
        "message": "Uploaded and deploying. Use this ID for everything.",
    }


# ── Status (unified — works with single ID) ────────────────────

@router.get("/deploy/{project_id}/status")
async def get_deploy_status(project_id: str):
    """Get full status: project info + deployment state + all data."""
    project = project_store.get(project_id)
    deployment = deployment_store.get(project_id)

    if not project and not deployment:
        raise HTTPException(status_code=404, detail="Not found")

    return {
        "id": project_id,
        "project": project.model_dump(mode="json") if project else None,
        "deployment": deployment.model_dump(mode="json") if deployment else None,
    }


# ── Helpers ──────────────────────────────────────────────────────

def _find_project_root(base: Path) -> Path:
    """Skip single wrapper directories to find actual project root."""
    entries = [e for e in base.iterdir() if not e.name.startswith(".") and e.name != "upload.zip"]
    if len(entries) == 1 and entries[0].is_dir():
        return _find_project_root(entries[0])
    return base
