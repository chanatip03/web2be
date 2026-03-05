"""Project management API endpoints."""

from __future__ import annotations

import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.deployment.core.config import settings
from app.deployment.core.exceptions import NotFoundError
from app.deployment.models.project import ProjectMetadata
from app.deployment.services.analyzer.file_scanner import build_file_tree
from app.deployment.services.deployer.pipeline import project_store, run_analysis

router = APIRouter(prefix="/api/projects", tags=["Projects"])


# ── Upload (ZIP) ─────────────────────────────────────────────────

@router.post("/upload")
async def upload_project(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(...),
    projectType: str = Form("auto"),
):
    """Upload a ZIP archive, extract it, and trigger background analysis."""
    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Save and extract ZIP
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

    # Find project root (skip wrapper directories)
    project_root = _find_project_root(project_dir)

    # If extracted into a subfolder, move contents up
    if project_root != project_dir:
        for item in project_root.iterdir():
            dest = project_dir / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))

    # Create metadata
    file_tree_dict = build_file_tree(project_dir)
    from app.deployment.models.project import FileNode
    try:
        file_tree = FileNode.model_validate(file_tree_dict)
    except Exception:
        file_tree = None

    project = ProjectMetadata(
        project_id=project_id,
        name=name,
        project_type=projectType if projectType != "auto" else "unknown",
        uploaded_at=datetime.now(),
        file_tree=file_tree,
    )
    project_store.save(project)

    # Trigger background analysis
    background_tasks.add_task(run_analysis, project_id, str(project_dir))

    return {
        "projectId": project_id,
        "project_id": project_id,
        "name": name,
        "status": "analyzing",
        "message": "Project uploaded. Analysis in progress.",
    }


# ── Upload folder ────────────────────────────────────────────────

@router.post("/upload-folder")
async def upload_folder(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    name: str = Form(...),
    projectType: str = Form("auto"),
):
    """Upload individual files with relative paths to reconstruct a folder."""
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
        project_type=projectType if projectType != "auto" else "unknown",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)
    background_tasks.add_task(run_analysis, project_id, str(project_dir))

    return {
        "projectId": project_id,
        "project_id": project_id,
        "name": name,
        "status": "analyzing",
    }


# ── Import from GitHub ──────────────────────────────────────────

@router.post("/import-github")
async def import_github(
    background_tasks: BackgroundTasks,
    repo_url: str = Form(""),
    repoUrl: str = Form(""),
    name: str = Form(""),
    projectType: str = Form("auto"),
    subdir: str = Form(""),
):
    """Clone a public GitHub repository and analyse it."""
    effective_repo_url = (repo_url or repoUrl or "").strip()
    if not effective_repo_url:
        raise HTTPException(status_code=400, detail="repoUrl is required")

    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    clone_target = project_dir / "repo"
    project_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["git", "clone", "--depth", "1", effective_repo_url, str(clone_target)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Git clone failed: {result.stderr}")

    # If subdir specified, use that as project root
    effective_root = clone_target / subdir if subdir else clone_target

    if not clone_target.exists() or not clone_target.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Git clone failed: repository content not found")

    if not effective_root.exists() or not effective_root.is_dir():
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Invalid subdir: {subdir}")

    # Move to project root level
    for item in effective_root.iterdir():
        if item.name == ".git":
            continue
        dest = project_dir / item.name
        shutil.move(str(item), str(dest))
    shutil.rmtree(clone_target, ignore_errors=True)

    proj_name = name or effective_repo_url.rstrip("/").split("/")[-1]
    project = ProjectMetadata(
        project_id=project_id,
        name=proj_name,
        project_type=projectType if projectType != "auto" else "unknown",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)
    background_tasks.add_task(run_analysis, project_id, str(project_dir))

    return {
        "projectId": project_id,
        "project_id": project_id,
        "name": proj_name,
        "status": "analyzing",
    }


@router.post("/inspect-github")
async def inspect_github_repo(repoUrl: str = Form(""), repo_url: str = Form("")):
    """Inspect top-level folders in a public GitHub repository."""
    target = (repoUrl or repo_url or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="repoUrl is required")

    with TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", target, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"Git clone failed: {result.stderr}")

        folders = sorted(
            [p.name for p in clone_dir.iterdir() if p.is_dir() and p.name != ".git"]
        )
        return {"folders": folders}


@router.get("/mock/list")
async def list_mock_projects():
    """List local mock project folders for quick demo imports."""
    base = Path(settings.data_dir) / "projects"
    if not base.exists():
        return []
    return [
        {"name": p.name, "path": str(p)}
        for p in sorted(base.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    ]


@router.post("/mock/import")
async def import_mock_project(
    background_tasks: BackgroundTasks,
    folder: str = Form(...),
    name: str = Form(""),
    projectType: str = Form("auto"),
):
    """Import a local mock folder into the managed projects area."""
    source = Path(folder)
    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=404, detail="Mock folder not found")

    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    shutil.copytree(source, project_dir)

    project = ProjectMetadata(
        project_id=project_id,
        name=name or source.name,
        project_type=projectType if projectType != "auto" else "unknown",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)
    background_tasks.add_task(run_analysis, project_id, str(project_dir))

    return {
        "projectId": project_id,
        "project_id": project_id,
        "name": project.name,
        "status": "analyzing",
    }

@router.post("/mock/earai")
async def import_mock_earai(background_tasks: BackgroundTasks):
    """Quick-import a built-in EarAI demo FastAPI project for testing/demo purposes."""
    import textwrap

    project_id = str(uuid.uuid4())
    project_dir = Path(settings.projects_dir) / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    _MAIN = textwrap.dedent(
        '''
        """EarAI Demo — sample FastAPI backend."""
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI(title="EarAI Demo")


        class EarRequest(BaseModel):
            text: str
            lang: str = "th"


        @app.get("/")
        def root():
            return {"service": "EarAI", "status": "ok"}


        @app.post("/transcribe")
        def transcribe(req: EarRequest):
            return {"text": req.text, "lang": req.lang, "result": "transcribed"}


        @app.get("/health")
        def health():
            return {"status": "healthy"}
        '''
    ).lstrip()

    _DOCKERFILE = textwrap.dedent(
        """
        FROM python:3.11-slim
        WORKDIR /app
        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt
        COPY . .
        EXPOSE 8000
        CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
        """
    ).lstrip()

    (project_dir / "main.py").write_text(_MAIN, encoding="utf-8")
    (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (project_dir / "Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
    (project_dir / "README.md").write_text(
        "# EarAI Demo\n\nSample FastAPI project — auto-generated for demo.\n",
        encoding="utf-8",
    )

    project = ProjectMetadata(
        project_id=project_id,
        name="EarAI Demo",
        project_type="fastapi",
        uploaded_at=datetime.now(),
    )
    project_store.save(project)
    background_tasks.add_task(run_analysis, project_id, str(project_dir))

    return {
        "projectId": project_id,
        "project_id": project_id,
        "name": "EarAI Demo",
        "status": "analyzing",
        "message": "EarAI demo project imported. Analysis running in background.",
    }

# ── Re-analyse ───────────────────────────────────────────────────────

@router.post("/{project_id}/re-analyze")
async def re_analyze(project_id: str, background_tasks: BackgroundTasks):
    """Wipe current analysis and re-run LLM analysis in background."""
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_dir = Path(settings.projects_dir) / project_id
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project files not found")

    # Clear previous analysis so status shows 'analyzing'
    project.analysis = None
    project.project_type = "unknown"
    project_store.save(project)

    background_tasks.add_task(run_analysis, project_id, str(project_dir))
    return {
        "project_id": project_id,
        "status": "analyzing",
        "message": "Re-analysis started in background",
    }


# ── Analysis status ─────────────────────────────────────────────────

@router.get("/{project_id}/analysis")
async def get_analysis(project_id: str):
    """Return analysis result and status (fast poll endpoint)."""
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": project_id,
        "analysis_complete": project.analysis is not None,
        "project_type": project.project_type,
        "analysis": project.analysis.model_dump(mode="json") if project.analysis else None,
    }


# ── List projects ───────────────────────────────────────────────

@router.get("")
async def list_projects():
    """List all known projects."""
    projects = project_store.list_all()
    return [
        {
            "project_id": p.project_id,
            "name": p.name,
            "project_type": p.project_type,
            "uploaded_at": p.uploaded_at.isoformat(),
            "has_analysis": p.analysis is not None,
        }
        for p in projects
    ]


# ── Get project detail ──────────────────────────────────────────

@router.get("/{project_id}")
async def get_project(project_id: str):
    """Get full project details including analysis."""
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump(mode="json")


# ── Delete project ───────────────────────────────────────────────

@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a project, stop its containers, and clean up all related data."""
    if not project_store.exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    # 1. Stop all running deployments and remove records for this project
    from app.deployment.services.deployer.pipeline import deployment_store
    from app.deployment.services.docker.client import docker_client

    stopped_deployments = []
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
        except Exception:
            pass  # Container may already be gone
        deployment_store.delete(dep.deployment_id)
        stopped_deployments.append(dep.deployment_id)

    # 2. Remove project files
    project_dir = Path(settings.projects_dir) / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)

    # 3. Remove bundle
    bundle_path = Path(settings.deployments_dir) / "bundles" / f"{project_id}.tar.gz"
    bundle_path.unlink(missing_ok=True)

    # 4. Remove project metadata
    project_store.delete(project_id)

    return {
        "message": f"Project {project_id} deleted",
        "stopped_deployments": stopped_deployments,
    }


# ── Helpers ──────────────────────────────────────────────────────

def _find_project_root(base: Path) -> Path:
    """Skip single wrapper directories to find actual project root."""
    entries = [e for e in base.iterdir() if not e.name.startswith(".") and e.name != "upload.zip"]
    if len(entries) == 1 and entries[0].is_dir():
        return _find_project_root(entries[0])
    return base
