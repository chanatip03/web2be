from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.assignment.repository import get_assignment_by_id
from app.core.classroom.repository import is_classroom_of_teacher
from app.core.classroommember.repository import is_student_in_classroom
from app.core.group.repository import get_user_group_by_assignment
from app.core.security_scan.fs import validate_submission, save_result
from app.core.security_scan.normalizer import normalize_code_result
from app.core.security_scan.snyk_code import scan_source_code
from app.core.user.repository import get_student_by_user_id, get_teacher_by_user_id
from app.db.database import SessionLocal
from app.deployment.core.config import settings
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.models.project import FileNode, ProjectMetadata
from app.deployment.services.docker.client import docker_client
from app.deployment.services.analyzer.file_scanner import build_file_tree
from app.deployment.services.deployer.pipeline import (
    deployment_store,
    project_store,
    run_deployment,
)
from app.models.schema import Project, SubmissionTypeEnum
from app.core.generatetestcase.services.runner import run_robot_tests_with_suite_content
from app.utils.r2 import (
    R2_PUBLIC_URL,
    get_file_bytes,
    upload_file as r2_upload_file,
)

from .dto import SubmissionAcceptedResponse, SubmissionArtifactListResponse
from .fs import (
    copy_artifact_into_submission,
    create_submission_root,
    extract_archive_to_source,
    get_source_dir,
    get_submission_root,
    read_manifest,
    register_artifact,
    resolve_artifact_path,
    save_uploaded_archive,
    set_artifact_download_urls,
    write_json_artifact,
    write_manifest,
)
from .manifest import SubmissionManifest, StepRecord, build_initial_manifest, touch_manifest, utc_now_iso
from app.utils.archive import delete_directory


_MODE_ALIASES = {
    "fe": "frontend-only",
    "frontend": "frontend-only",
    "frontend-only": "frontend-only",
    "static": "frontend-only",
    "static-html": "frontend-only",
    "be": "backend-only",
    "backend": "backend-only",
    "backend-only": "backend-only",
    "api": "backend-only",
    "project": "fullstack",
    "fullstack": "fullstack",
    "fullstack+db": "fullstack",
    "fullstack-db": "fullstack",
    "fullstack-sql": "fullstack",
}


def _normalize_mode_name(name: str | None) -> Optional[str]:
    if not name:
        return None
    normalized = name.strip().lower()
    if normalized in _MODE_ALIASES:
        return _MODE_ALIASES[normalized]
    if "full" in normalized:
        return "fullstack"
    if "front" in normalized and "back" not in normalized:
        return "frontend-only"
    if "back" in normalized and "front" not in normalized:
        return "backend-only"
    return None


def _resolve_execution_mode(assignment) -> str:
    project_type = getattr(getattr(assignment, "project_type", None), "name", None)
    execution_mode = _normalize_mode_name(project_type)
    if execution_mode:
        return execution_mode
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported project type for submission flow: {project_type or assignment.project_type_id}",
    )


def _resolve_execution_mode_from_payload_or_assignment(payload, assignment) -> str:
    """Prefer explicit client-provided mode; fall back to assignment.project_type."""
    # allow either "project_type" or "deploy_mode" from client
    requested = None
    try:
        requested = getattr(payload, "project_type", None) or getattr(payload, "deploy_mode", None)
    except Exception:
        requested = None

    requested_mode = _normalize_mode_name(requested)
    if requested_mode:
        return requested_mode

    return _resolve_execution_mode(assignment)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_assignment_availability(assignment) -> bool:
    """Validate the assignment is accessible and return True if the submission is late.

    Raises HTTP 404 if the assignment is deleted.
    Raises HTTP 403 if the assignment has not opened yet.
    Returns True if the due_date has passed (late submission), False otherwise.
    """
    if assignment.deleted_date is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    now = datetime.now(timezone.utc)
    start_date = _coerce_utc(getattr(assignment, "start_date", None))
    due_date = _coerce_utc(getattr(assignment, "due_date", None))

    if start_date and now < start_date:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment has not opened yet")

    # Past due_date → allow submission but flag as late
    if due_date and now > due_date:
        return True

    return False


def _set_step_running(manifest: SubmissionManifest, step_name: str, **details) -> SubmissionManifest:
    step = manifest.steps.get(step_name) or StepRecord()
    step.status = "running"
    step.started_at = step.started_at or utc_now_iso()
    step.error = None
    if details:
        step.details.update(details)
    manifest.steps[step_name] = step
    touch_manifest(manifest)
    return manifest


def _set_step_finished(
    manifest: SubmissionManifest,
    step_name: str,
    step_status: str,
    *,
    error: Optional[str] = None,
    **details,
) -> SubmissionManifest:
    step = manifest.steps.get(step_name) or StepRecord()
    step.status = step_status
    step.finished_at = utc_now_iso()
    step.error = error
    if details:
        step.details.update(details)
    manifest.steps[step_name] = step
    touch_manifest(manifest)
    return manifest


def _update_pipeline_status(manifest: SubmissionManifest) -> SubmissionManifest:
    relevant_statuses = [
        step.status
        for step_name, step in manifest.steps.items()
        if step_name not in {"prepare", "plagiarism"}
    ]
    if any(step_status == "running" for step_status in relevant_statuses):
        manifest.pipeline_status = "running"
    elif any(step_status == "error" for step_status in relevant_statuses):
        successful = any(step_status in {"success", "skipped"} for step_status in relevant_statuses)
        manifest.pipeline_status = "partial_success" if successful else "error"
    else:
        manifest.pipeline_status = "success"
    touch_manifest(manifest)
    return manifest


def _submission_source_name(source_ref: str | None, source_type: str) -> str:
    if source_type == "zip" and source_ref:
        return Path(source_ref).stem or "submission"
    if source_ref:
        return source_ref.rstrip("/").split("/")[-1] or "submission"
    return "submission"


def _resolve_test_runner_preview_url(preview_url: str) -> str:
    parsed = urlparse(preview_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return preview_url

    host = "host.docker.internal"
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host
    return urlunparse(parsed._replace(netloc=netloc))


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _docker_compose_available() -> bool:
    if not _command_exists("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return False
    return result.returncode == 0


def _ensure_submission_runtime_ready(
    *,
    execution_mode: str,
    uses_repo_url: bool,
    requires_testcase: bool,
) -> None:
    failures: list[str] = []

    if not docker_client.is_available():
        failures.append("Docker daemon is unavailable. Start Docker Desktop and ensure the selected context is running.")

    if execution_mode == "fullstack" and not _docker_compose_available():
        failures.append("`docker compose` is unavailable. Install Docker Compose v2 or ensure Docker Desktop is configured correctly.")

    if uses_repo_url and not _command_exists("git"):
        failures.append("`git` is unavailable in PATH, so repository submissions cannot be cloned.")

    if not _command_exists("snyk"):
        failures.append("`snyk` is unavailable in PATH, so the cybersecurity scan step cannot run.")

    if requires_testcase and importlib.util.find_spec("robot") is None:
        failures.append(
            f"Robot Framework is not installed in the active Python environment ({sys.executable})."
        )

    if failures:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Submission runtime prerequisites are not satisfied.",
                "issues": failures,
            },
        )


def _create_submission_records(
    db: Session,
    *,
    assignment_id: int,
    student_id: int,
    group_id: Optional[int],
    is_group: bool,
    source_type: str,
    source_ref: str | None,
    env: str | None,
    execution_mode: str,
    submission_uuid: str,
    is_late: bool = False,
) -> Project:
    """Create or Update Project.

    - Group assignment:    Updates/Creates based on group_id and assignment_id
    - Individual:          Updates/Creates based on student_id and assignment_id
    """
    submission_type = (
        SubmissionTypeEnum.file if source_type == "zip" else SubmissionTypeEnum.github
    )

    initial_source_url = source_ref or ""

    project = None
    if is_group and group_id:
        project = db.query(Project).filter(Project.assignment_id == assignment_id, Project.group_id == group_id).first()
    elif not is_group and student_id:
        project = db.query(Project).filter(Project.assignment_id == assignment_id, Project.student_id == student_id).first()

    if project:
        logger.info("Updating existing project record for assignment %s with UUID: %s", assignment_id, submission_uuid)
        project.submission_type = submission_type
        project.submission_uuid = submission_uuid
        project.project_source_url = initial_source_url
        project.env = env or execution_mode
        project.is_late = is_late
        
        # Clear previous pipeline results as a new one is starting
        project.cybersecurity_result = None
        project.testcase_result = None
        project.container_id = None
        project.container_resource = None
        project.score = None
        project.feedback = None
    else:
        logger.info("Creating project record for assignment %s with UUID: %s", assignment_id, submission_uuid)
        project = Project(
            assignment_id=assignment_id,
            group_id=group_id if is_group else None,
            student_id=None if is_group else student_id,
            submission_type=submission_type,
            submission_uuid=submission_uuid,
            project_source_url=initial_source_url,
            env=env or execution_mode,
            is_late=is_late,
        )
        db.add(project)

    db.flush()
    db.commit()
    db.refresh(project)
    return project


def _persist_project_results(
    project_db_id: int | None,
    *,
    cybersecurity_result: dict | None = None,
    testcase_result: dict | None = None,
    project_source_url: str | None = None,
    container_id: str | None = None,
    container_resource: str | None = None,
) -> None:
    if project_db_id is None:
        return

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_db_id).first()
        if not project:
            return
        if cybersecurity_result is not None:
            project.cybersecurity_result = json.dumps(cybersecurity_result, ensure_ascii=False)
        if testcase_result is not None:
            project.testcase_result = json.dumps(testcase_result, ensure_ascii=False)
        if project_source_url is not None:
            project.project_source_url = project_source_url
        if container_id is not None:
            project.container_id = container_id
        if container_resource is not None:
            project.container_resource = container_resource
        db.commit()
    finally:
        db.close()
def _ensure_submission_access(
    manifest: SubmissionManifest,
    db: Session,
    current_user,
) -> SubmissionManifest:
    role = current_user["role"]
    if role == "admin":
        return manifest

    if role == "student":
        if manifest.submitted_by_user_id != current_user["id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access denied")
        return manifest

    if role == "teacher":
        teacher = get_teacher_by_user_id(db, current_user["id"])
        assignment = get_assignment_by_id(db, manifest.assignment_id)
        if not teacher or not assignment:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access denied")
        if not is_classroom_of_teacher(db, assignment.classroom_id, teacher.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access denied")
        return manifest

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Submission access denied")


async def create_submission_service(
    *,
    assignment_id: int,
    payload,
    upload_file: UploadFile | None,
    background_tasks: BackgroundTasks,
    db: Session,
    current_user,
) -> SubmissionAcceptedResponse:
    if current_user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students can submit assignments")

    if bool(upload_file) == bool(payload.repo_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of file upload or repo_url",
        )

    student = get_student_by_user_id(db, current_user["id"])
    if not student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student profile not found")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    is_late = _validate_assignment_availability(assignment)

    if not is_student_in_classroom(db, assignment.classroom_id, student.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student is not in the assignment classroom")

    # ── Resolve group_id ────────────────────────────────────────────
    is_group = bool(assignment.is_group)
    resolved_group_id: Optional[int] = None

    if is_group:
        # Prefer the group_id sent by the frontend; fall back to DB lookup.
        if payload.group_id:
            resolved_group_id = payload.group_id
        else:
            group = get_user_group_by_assignment(db, student.id, assignment_id)
            if group:
                resolved_group_id = group.id

        if resolved_group_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group assignment requires a group. Please join or create a group first.",
            )

    submission_id = str(uuid.uuid4())
    execution_mode = _resolve_execution_mode_from_payload_or_assignment(payload, assignment)
    requires_testcase = execution_mode in {"frontend-only", "backend-only"} and bool(assignment.testcase_url)
    _ensure_submission_runtime_ready(
        execution_mode=execution_mode,
        uses_repo_url=bool(payload.repo_url),
        requires_testcase=requires_testcase,
    )

    create_submission_root(submission_id)

    source_dir = get_source_dir(submission_id)
    source_type: str
    source_ref: str | None

    if upload_file:
        source_type = "zip"
        source_ref = upload_file.filename or "submission.zip"
        archive_bytes = await upload_file.read()
        archive_path = save_uploaded_archive(submission_id, source_ref, archive_bytes)
        extract_archive_to_source(archive_path, source_dir)
    else:
        source_type = "repo_url"
        source_ref = payload.repo_url
        _clone_repo_to_source(payload.repo_url, source_dir)

    project = _create_submission_records(
        db,
        assignment_id=assignment.id,
        student_id=student.id,
        group_id=resolved_group_id,
        is_group=is_group,
        source_type=source_type,
        source_ref=source_ref,
        env=payload.env,
        execution_mode=execution_mode,
        submission_uuid=submission_id,
        is_late=is_late,
    )

    manifest = build_initial_manifest(
        submission_id=submission_id,
        assignment_id=assignment_id,
        submitted_by_user_id=current_user["id"],
        student_id=student.id,
        group_id=resolved_group_id,
        project_db_id=project.id,
        execution_mode=execution_mode,
        source_type=source_type,
        source_ref=source_ref,
        env=payload.env,
        testcase_source_url=assignment.testcase_url,
        is_late=is_late,
    )

    if upload_file:
        archive_path = get_submission_root(submission_id) / "original" / Path(source_ref).name
        artifact = register_artifact(
            manifest,
            absolute_path=archive_path,
            category="original",
            name=archive_path.name,
            content_type=upload_file.content_type or "application/zip",
        )
        artifact.download_url = f"/api/submission/{submission_id}/artifacts/{artifact.artifact_id}"

    set_artifact_download_urls(manifest)
    write_manifest(manifest)
    background_tasks.add_task(run_submission_pipeline_sync, submission_id)

    return SubmissionAcceptedResponse(
        submission_id=submission_id,
        assignment_id=assignment_id,
        execution_mode=execution_mode,
        pipeline_status=manifest.pipeline_status,
        is_late=is_late,
        status_url=f"/api/submission/{submission_id}",
        artifact_list_url=f"/api/submission/{submission_id}/artifacts",
    )


def _sanitize_repo_url(url: str) -> str:
    """Strip whitespace / newlines that can sneak in via copy-paste."""
    return "".join(url.split()).strip()


def _clone_repo_to_source(repo_url: str, source_dir: Path) -> None:
    clean_url = _sanitize_repo_url(repo_url)

    # Basic validation — git URLs must start with http(s):// or git@
    if not (clean_url.startswith("https://") or clean_url.startswith("http://") or clean_url.startswith("git@")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid repository URL: must start with https://, http://, or git@",
        )

    source_dir.mkdir(parents=True, exist_ok=True)

    # Inherit the current environment and disable ALL credential prompting.
    # Without this, git tries to open a TTY for username/password input which
    # fails with "No such device or address" inside Docker / background threads.
    import os as _os
    git_env = {**_os.environ}
    git_env["GIT_TERMINAL_PROMPT"] = "0"   # never prompt on terminal
    git_env["GIT_ASKPASS"] = "echo"         # return empty string for any credential ask
    git_env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no"

    result = subprocess.run(
        [
            "git", "clone",
            "-c", "credential.helper=",      # disable stored credential helpers
            "--depth", "1",
            clean_url,
            str(source_dir),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=git_env,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        # Produce friendlier messages for the most common failure modes
        if "could not read Username" in stderr or "Authentication failed" in stderr:
            detail = (
                "Git clone failed: the repository requires authentication. "
                "Please make sure the repository is public, or use a token in the URL "
                "(e.g. https://<token>@github.com/user/repo.git)."
            )
        elif "Repository not found" in stderr or "not found" in stderr.lower():
            detail = f"Git clone failed: repository not found at {clean_url}"
        else:
            detail = f"Git clone failed: {stderr}"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    shutil.rmtree(source_dir / ".git", ignore_errors=True)



# ── Submission container auto-stop timers ─────────────────────────────────────
# Uses the same pattern as admin/service.py _cleanup_timers
import threading as _threading

_submission_cleanup_timers: dict[str, _threading.Timer] = {}
_submission_cleanup_timers_lock = _threading.Lock()


def _do_teardown_now(submission_id: str) -> None:
    """Docker stop/remove + disk cleanup, mirroring admin._cleanup_stopped_deployment_runtime.

    Cleanup order:
    1. compose down  (preferred — uses compose_file_path when available)
    2. Fallback: stop + remove individual container from DB record
    3. Remove Docker images for this deployment
    4. Update deployment_store (mark stopped, clear URLs/ports)
    5. Clean preview session if active
    6. Disk cleanup via delete_directory(submission_id)
    """
    logger.info("Auto-stop timer fired for submission %s — tearing down containers", submission_id)

    from app.deployment.services.deployer.pipeline import deployment_store
    from app.utils.archive import delete_directory

    # ── 1. Fetch deployment record ────────────────────────────────────
    dep = None
    try:
        dep = deployment_store.get(submission_id)
    except Exception as exc:
        logger.warning("Could not read deployment_store for %s: %s", submission_id, exc)

    # ── 2. compose down (preferred) ──────────────────────────────────
    compose_succeeded = False
    if dep and dep.compose_project:
        compose_project = dep.compose_project

        # Resolve compose working dir — same priority as admin._cleanup_stopped_deployment_runtime
        compose_dir: str | None = None
        if dep.compose_file_path:
            compose_dir = str(Path(dep.compose_file_path).parent)
        else:
            from app.deployment.core.config import settings as _dep_settings
            _runtime_candidates = [
                Path(_dep_settings.projects_dir)    / submission_id,
                Path(_dep_settings.data_dir)        / "previews"    / submission_id,
                Path(_dep_settings.deployments_dir) / "activations" / submission_id,
            ]
            _found = next((p for p in _runtime_candidates if p.exists()), None)
            if _found:
                compose_dir = str(_found)

        try:
            docker_client.compose_down(compose_dir or "/", compose_project, remove_volumes=True)
            logger.info("compose_down succeeded for submission %s (project=%s)", submission_id, compose_project)
            compose_succeeded = True
        except Exception as exc:
            logger.warning("compose_down failed for %s: %s — will try per-container removal", submission_id, exc)


    # ── 3. Fallback: stop + remove individual container ───────────────
    if not compose_succeeded:
        try:
            from app.db.database import SessionLocal as _SL
            from app.models.schema import Project as _Project
            with _SL() as _db:
                proj = _db.query(_Project).filter(_Project.submission_uuid == submission_id).first()
                container_name = proj.container_id if proj else None
            if container_name:
                docker_client.stop_container(container_name)
                docker_client.remove_container(container_name)
                logger.info("Stopped and removed container %s for submission %s", container_name, submission_id)
            elif dep and dep.container_id:
                docker_client.stop_container(dep.container_id)
                docker_client.remove_container(dep.container_id)
                logger.info("Stopped and removed container %s (from dep store) for submission %s", dep.container_id, submission_id)
        except Exception as exc:
            logger.warning("Fallback container removal failed for %s: %s", submission_id, exc)

    # ── 4. Remove Docker images ──────────────────────────────────────
    if dep:
        try:
            from app.core.admin.service import _collect_deployment_image_refs
            image_refs = _collect_deployment_image_refs(dep)
            if image_refs:
                docker_client.remove_images(image_refs)
                logger.info("Removed %d image(s) for submission %s", len(image_refs), submission_id)
        except Exception as exc:
            logger.warning("Image removal failed for %s: %s", submission_id, exc)

    # ── 5. Update deployment_store ───────────────────────────────────
    if dep:
        try:
            dep.status = "stopped"
            dep.container_state = "removed"
            dep.container_id = None
            dep.preview_url = None
            dep.api_url = None
            dep.host_port = None
            dep.extra_ports = []
            dep.service_ports = []
            deployment_store.save(dep)
        except Exception as exc:
            logger.warning("Failed to update deployment_store for %s: %s", submission_id, exc)

    # ── 6. Clean preview session (removes loaded images) ─────────────
    try:
        from app.deployment.api.submission_preview import _sessions, _teardown as _preview_teardown
        if submission_id in _sessions:
            _preview_teardown(submission_id)
            logger.info("Cleaned up preview session for %s", submission_id)
    except Exception as exc:
        logger.warning("Failed to clean preview session for %s: %s", submission_id, exc)

    # ── 7. Disk cleanup ──────────────────────────────────────────────
    try:
        delete_directory(submission_id)
        logger.info("Disk cleanup succeeded for submission %s", submission_id)
    except Exception as exc:
        logger.warning("Disk cleanup failed for %s: %s", submission_id, exc)

    # Remove timer reference
    with _submission_cleanup_timers_lock:
        _submission_cleanup_timers.pop(submission_id, None)






def _schedule_submission_cleanup(submission_id: str, delay_seconds: float | None = None) -> None:
    """Schedule a deferred container stop + disk cleanup for *submission_id*.

    Can be called:
    - from the submission pipeline ``finally`` block (auto-stop after pipeline)
    - from an "activate container" flow (auto-stop after preview window)

    If called again before the timer fires, the existing timer is cancelled and
    a fresh one is started, effectively extending the window.

    Args:
        submission_id: The submission UUID to clean up.
        delay_seconds: Override the configured delay. Defaults to
            ``settings.container_auto_stop_delay_seconds`` (5 minutes).
    """
    if delay_seconds is None:
        delay_seconds = float(settings.container_auto_stop_delay_seconds)

    with _submission_cleanup_timers_lock:
        existing = _submission_cleanup_timers.pop(submission_id, None)
        if existing is not None:
            existing.cancel()

        timer = _threading.Timer(delay_seconds, _do_teardown_now, args=(submission_id,))
        timer.daemon = True
        _submission_cleanup_timers[submission_id] = timer
        timer.start()

    logger.info(
        "Scheduled auto-stop for submission %s in %.0f seconds (%.1f min)",
        submission_id, delay_seconds, delay_seconds / 60,
    )


def _teardown_deployment_containers(submission_id: str) -> None:
    """Schedule the container teardown 5 minutes after the pipeline finishes.

    Delegates to ``_schedule_submission_cleanup`` which uses a ``threading.Timer``
    so the containers remain accessible for a short review window before being
    automatically stopped and cleaned up.
    """
    _schedule_submission_cleanup(submission_id)


def run_submission_pipeline_sync(submission_id: str) -> None:
    asyncio.run(run_submission_pipeline(submission_id))


async def run_submission_pipeline(submission_id: str) -> None:
    manifest = read_manifest(submission_id)
    manifest.pipeline_status = "running"
    write_manifest(manifest)

    try:
        await _run_cyber_scan_step(manifest)
        await _run_deployment_step(manifest)
        await _run_testcase_step(manifest)
        await _run_r2_upload_step(manifest)
    except Exception as exc:
        manifest = read_manifest(submission_id)
        manifest.pipeline_status = "error"
        manifest.deployment = manifest.deployment or {}
        manifest.deployment.setdefault("message", "Submission pipeline stopped unexpectedly.")
        manifest.deployment["unexpected_error"] = str(exc)
        write_manifest(manifest)
    else:
        # All steps completed without raising — compute final pipeline_status
        manifest = read_manifest(submission_id)
        _update_pipeline_status(manifest)
        write_manifest(manifest)
    finally:
        # Always tear down containers after the pipeline finishes (success or
        # error), then remove this submission's local working directories.
        _teardown_deployment_containers(submission_id)


async def _run_cyber_scan_step(manifest: SubmissionManifest) -> None:
    manifest = _set_step_running(manifest, "cyber")
    write_manifest(manifest)

    source_dir = get_source_dir(manifest.submission_id)
    try:
        validation = validate_submission(source_dir)
        if not validation["has_files"]:
            raise RuntimeError("No source code files found in submission")
        raw_result = scan_source_code(source_dir)
        normalized = normalize_code_result(raw_result)
        cyber_path = write_json_artifact(manifest.submission_id, "cyber", "scan.json", normalized)
        
        # Save a duplicate to the global RESULTS_DIR so it's visible in the host volume
        try:
            save_result(manifest.submission_id, normalized)
        except Exception:
            pass
            
        artifact = register_artifact(
            manifest,
            absolute_path=cyber_path,
            category="cyber",
            name="scan.json",
            content_type="application/json",
        )
        set_artifact_download_urls(manifest)
        cyber_download_url = artifact.download_url
        cyber_download_source = "local"
        try:
            key = f"submissions/{manifest.submission_id}/scan.json"
            _, uploaded_url = r2_upload_file(key, cyber_path.read_bytes(), content_type="application/json")
            manifest.r2_artifacts["cyber_scan"] = uploaded_url
            cyber_download_url = uploaded_url
            cyber_download_source = "r2"
        except Exception:
            pass
        manifest.cyber = {
            **normalized,
            "status": "success",
            "languages": validation["languages"],
            "file_count": validation["file_count"],
            "issues_found": normalized.get("issues_found", 0),
            "artifact_id": artifact.artifact_id,
            "download_url": cyber_download_url,
            "fallback_download_url": artifact.download_url,
            "download_source": cyber_download_source,
        }
        _set_step_finished(
            manifest,
            "cyber",
            "success",
            issues_found=normalized.get("issues_found", 0),
        )
    except Exception as exc:
        manifest.cyber = {
            "status": "error",
            "message": str(exc),
        }
        _set_step_finished(manifest, "cyber", "error", error=str(exc))
    _persist_project_results(manifest.project_db_id, cybersecurity_result=manifest.cyber)
    write_manifest(manifest)


async def _run_deployment_step(manifest: SubmissionManifest) -> None:
    manifest = _set_step_running(manifest, "deployment", mode=manifest.execution_mode)
    write_manifest(manifest)

    submission_id = manifest.submission_id
    project_id = submission_id
    deployment_id = submission_id
    project_name = _submission_source_name(manifest.source_ref, manifest.source_type)
    project_dir = _materialize_deployment_project(submission_id)

    # NEW: Zip project_dir and upload to R2 for project_source_url
    try:
        from app.utils.archive import zip_directory
        from app.utils.r2 import upload_file
        import logging
        logger = logging.getLogger(__name__)

        zipped_source = zip_directory(str(project_dir))
        source_key = f"submissions/{submission_id}.zip"
        _, source_url = upload_file(source_key, zipped_source, content_type="application/zip")
        
        # Persist the newly uploaded source URL
        _persist_project_results(
            manifest.project_db_id,
            project_source_url=source_url,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to zip and upload source for {submission_id}: {e}")

    file_tree = None
    try:
        file_tree = FileNode.model_validate(build_file_tree(project_dir))
    except Exception:
        file_tree = None

    project_store.save(
        ProjectMetadata(
            project_id=project_id,
            name=project_name,
            project_type=manifest.execution_mode,
            uploaded_at=datetime.now(),
            file_tree=file_tree,
        )
    )
    deployment_store.save(
        DeploymentStatus(
            deployment_id=deployment_id,
            project_id=project_id,
            project_db_id=manifest.project_db_id,
            project_name=project_name,
            status="analyzing",
            current_step=1,
            total_steps=5,
            updated_at=datetime.now(),
        )
    )

    # Pass execution_mode directly — it already matches what the pipeline expects
    # (frontend-only | backend-only | fullstack). None means auto-detect.
    deploy_mode = manifest.execution_mode if manifest.execution_mode != "fullstack" else None
    await run_deployment(deployment_id, project_id, deploy_mode)

    deployment = deployment_store.get(deployment_id)
    bundle_path = Path(settings.deployments_dir) / "bundles" / f"{project_id}.tar.gz"
    build_logs_path = Path(settings.projects_dir) / project_id / ".logs" / f"build_logs_{deployment_id}.txt"

    artifact_ids: dict[str, str] = {}
    if bundle_path.exists():
        copied_bundle = copy_artifact_into_submission(submission_id, bundle_path, "deployment")
        bundle_artifact = register_artifact(
            manifest,
            absolute_path=copied_bundle,
            category="deployment",
            name=copied_bundle.name,
            content_type="application/gzip",
        )
        artifact_ids["bundle"] = bundle_artifact.artifact_id

    if build_logs_path.exists():
        copied_logs = copy_artifact_into_submission(submission_id, build_logs_path, "deployment")
        logs_artifact = register_artifact(
            manifest,
            absolute_path=copied_logs,
            category="deployment",
            name=copied_logs.name,
            content_type="text/plain",
        )
        artifact_ids["build_logs"] = logs_artifact.artifact_id

    set_artifact_download_urls(manifest)

    if not deployment or deployment.status != "success":
        error_message = (deployment.error_message if deployment else None) or "Deployment metadata not found"
        manifest.deployment = {
            "status": "error",
            "deployment_id": deployment_id,
            "project_id": project_id,
            "deploy_mode": manifest.execution_mode,
            "message": error_message,
            "artifacts": artifact_ids,
        }
        _set_step_finished(manifest, "deployment", "error", error=error_message)
        write_manifest(manifest)
        return

    # Build preview URL using the deployment object's own method (has fallback logic)
    preview_url = deployment.get_primary_url()

    # service_ports is a list of ServicePortMapping objects — serialize to dict
    service_ports_data = []
    if deployment.service_ports:
        for sp in deployment.service_ports:
            if hasattr(sp, "model_dump"):
                service_ports_data.append(sp.model_dump(mode="json"))
            elif isinstance(sp, dict):
                service_ports_data.append(sp)

    manifest.deployment = {
        "status": "success",
        "deployment_id": deployment.deployment_id,
        "project_id": deployment.project_id,
        "deploy_mode": deployment.deploy_mode,
        "preview_url": preview_url,
        "api_url": deployment.api_url,
        "compose_services": deployment.compose_services,
        "service_ports": service_ports_data,
        "artifacts": artifact_ids,
    }
    _set_step_finished(
        manifest,
        "deployment",
        "success",
        preview_url=preview_url,
    )
    # Persist the container_id to the Project record so it can be referenced later
    # For compose deployments: get all container names in this compose project
    # For single container deployments: use the container_id returned by the builder
    final_container_id = deployment.container_id
    if deployment.compose_project:
        try:
            import subprocess
            res = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}",
                 "--filter", f"label=com.docker.compose.project={deployment.compose_project}"],
                capture_output=True, text=True
            )
            c_ids = [cid.strip() for cid in res.stdout.strip().split('\n') if cid.strip()]
            if c_ids:
                # Store only the first container name — compose_project already stored separately
                final_container_id = c_ids[0]
                logger.info("Resolved compose container name: %s (project=%s)",
                            final_container_id, deployment.compose_project)
        except Exception as e:
            logger.warning("Failed to resolve compose container names: %s", e)

    # NOTE: removed dangerous `docker ps --latest` fallback which could pick up
    # a container belonging to a completely different submission.

    container_resource_url = None
    target_deployments_dir = Path(settings.data_dir) / "submissions" / submission_id / "artifacts" / "deployment"
        
    if target_deployments_dir.exists() and target_deployments_dir.is_dir():
        try:
            from app.utils.r2 import upload_file
            tar_files = list(target_deployments_dir.glob("*.tar.gz"))
            if tar_files:
                tar_path = tar_files[0]
                tar_data = tar_path.read_bytes()
                key = f"submissions/{submission_id}/{tar_path.name}"
                _, container_resource_url = upload_file(key, tar_data, content_type="application/gzip")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to upload deployment tar artifact for {submission_id}: {e}")

    _persist_project_results(
        manifest.project_db_id,
        container_id=final_container_id,
        container_resource=container_resource_url,
    )
    write_manifest(manifest)


async def _run_testcase_step(manifest: SubmissionManifest) -> None:
    mode_requires_testcase = manifest.execution_mode in {"frontend-only", "backend-only"}
    preview_url = manifest.deployment.get("preview_url")
    if not mode_requires_testcase:
        manifest.testcase = {
            "status": "skipped",
            "message": "Execution mode does not require testcase.",
        }
        _set_step_finished(manifest, "testcase", "skipped", message="Mode does not require testcase")
        write_manifest(manifest)
        return

    if manifest.steps.get("deployment") and manifest.steps["deployment"].status == "error":
        manifest.testcase = {
            "status": "skipped",
            "message": "Deployment failed, testcase skipped.",
        }
        _set_step_finished(manifest, "testcase", "skipped", message="Deployment failed")
        write_manifest(manifest)
        return

    if not manifest.testcase_source_url:
        manifest.testcase = {
            "status": "skipped",
            "message": "Assignment does not have a testcase file configured.",
        }
        _set_step_finished(manifest, "testcase", "skipped", message="No testcase configured")
        write_manifest(manifest)
        return

    if not preview_url:
        manifest.testcase = {
            "status": "skipped",
            "message": "Preview URL is unavailable, testcase skipped.",
        }
        _set_step_finished(manifest, "testcase", "skipped", message="Preview URL unavailable")
        write_manifest(manifest)
        return

    manifest = _set_step_running(manifest, "testcase", preview_url=preview_url)
    write_manifest(manifest)

    try:
        suite_content = await _load_testcase_suite_content(manifest.testcase_source_url)
        testcase_base_url = _resolve_test_runner_preview_url(preview_url.rstrip("/"))
        suite_content = suite_content.replace("http://localhost:3000", testcase_base_url)

        suite_dir = get_submission_root(manifest.submission_id) / "artifacts" / "testcase"
        suite_dir.mkdir(parents=True, exist_ok=True)
        suite_path = suite_dir / "test_suite.robot"
        suite_path.write_text(suite_content, encoding="utf-8")
        suite_artifact = register_artifact(
            manifest,
            absolute_path=suite_path,
            category="testcase",
            name="test_suite.robot",
            content_type="text/plain",
        )

        result = await run_robot_tests_with_suite_content(
            manifest.submission_id,
            suite_content,
            definition_test_id=f"submission-{manifest.submission_id}",
            suite_version=1,
        )

        testcase_artifacts = {
            "suite": suite_artifact.artifact_id,
        }
        testcase_urls: dict[str, str] = {}
        try:
            key = f"submissions/{manifest.submission_id}/testcase/test_suite.robot"
            _, uploaded_url = r2_upload_file(key, suite_path.read_bytes(), content_type="text/plain")
            testcase_urls["test_suite.robot"] = uploaded_url
        except Exception:
            pass
        result_dir = Path(settings.projects_dir) / manifest.submission_id / "tests" / "results" / result.test_id
        for filename, content_type in (
            ("report.html", "text/html"),
            ("log.html", "text/html"),
            ("output.xml", "application/xml"),
        ):
            source_path = result_dir / filename
            if not source_path.exists():
                continue
            copied = copy_artifact_into_submission(manifest.submission_id, source_path, "testcase")
            artifact = register_artifact(
                manifest,
                absolute_path=copied,
                category="testcase",
                name=filename,
                content_type=content_type,
            )
            testcase_artifacts[filename] = artifact.artifact_id
            try:
                key = f"submissions/{manifest.submission_id}/testcase/{filename}"
                _, uploaded_url = r2_upload_file(key, copied.read_bytes(), content_type=content_type)
                testcase_urls[filename] = uploaded_url
            except Exception:
                pass

        set_artifact_download_urls(manifest)
        manifest.testcase = {
            "status": result.status,
            "run_id": result.test_id,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "case_results": result.case_results,
            "artifacts": testcase_artifacts,
            "artifact_urls": testcase_urls,
            "artifact_source": "r2" if testcase_urls else "local",
            "log_url": testcase_urls.get("log.html"),
            "output_url": testcase_urls.get("output.xml"),
            "report_url": testcase_urls.get("report.html"),
        }

        if result.status == "error":
            _set_step_finished(manifest, "testcase", "error", error=result.output[-500:])
        elif result.status == "failed":
            _set_step_finished(
                manifest,
                "testcase",
                "error",
                error=f"{result.failed} testcase(s) failed",
                testcase_status=result.status,
                passed=result.passed,
                failed=result.failed,
            )
        else:
            _set_step_finished(
                manifest,
                "testcase",
                "success",
                testcase_status=result.status,
                passed=result.passed,
                failed=result.failed,
            )
    except Exception as exc:
        manifest.testcase = {
            "status": "error",
            "message": str(exc),
        }
        _set_step_finished(manifest, "testcase", "error", error=str(exc))

    _persist_project_results(manifest.project_db_id, testcase_result=manifest.testcase)
    write_manifest(manifest)


async def _run_r2_upload_step(manifest: SubmissionManifest) -> None:
    """Upload source zip and deployment bundle to Cloudflare R2.

    Runs as the final step after cyber, deployment, and testcase.
    Updates project.project_source_url in DB with the R2 URL of the source.
    Failures are non-fatal; they are logged into manifest.r2_artifacts.
    """
    r2_results: dict[str, str] = {}
    submission_id = manifest.submission_id

    # 1. Upload source zip  ────────────────────────────────────────
    if manifest.source_type == "zip":
        original_dir = get_submission_root(submission_id) / "original"
        zip_files = list(original_dir.glob("*.zip")) if original_dir.exists() else []
        if zip_files:
            zip_path = zip_files[0]
            try:
                key = f"submissions/{submission_id}/source.zip"
                _, url = r2_upload_file(key, zip_path.read_bytes(), content_type="application/zip")
                r2_results["source_zip"] = url
                # Update DB so project.project_source_url reflects the R2 location
                _persist_project_results(
                    manifest.project_db_id,
                    project_source_url=url,
                )
            except Exception as exc:
                r2_results["source_zip_error"] = str(exc)
    elif manifest.source_type == "repo_url" and manifest.source_ref:
        # For repo submissions the source URL is already the GitHub link
        _persist_project_results(
            manifest.project_db_id,
            project_source_url=manifest.source_ref,
        )
        r2_results["source_repo_url"] = manifest.source_ref

    # 2. Upload deployment bundle (.tar.gz) ────────────────────────
    bundle_dir = get_submission_root(submission_id) / "artifacts" / "deployment"
    bundle_files = list(bundle_dir.glob("*.tar.gz")) if bundle_dir.exists() else []
    if bundle_files:
        bundle_path = bundle_files[0]
        try:
            key = f"submissions/{submission_id}/bundle.tar.gz"
            _, url = r2_upload_file(key, bundle_path.read_bytes(), content_type="application/gzip")
            r2_results["bundle"] = url
            
            # Ensure DB is updated to match the final R2 URL where it successfully lands
            _persist_project_results(
                manifest.project_db_id,
                container_resource=url,
            )
        except Exception as exc:
            r2_results["bundle_error"] = str(exc)

    # 3. Upload cyber scan result JSON ─────────────────────────────
    cyber_dir = get_submission_root(submission_id) / "artifacts" / "cyber"
    scan_file = cyber_dir / "scan.json"
    if scan_file.exists():
        try:
            key = f"submissions/{submission_id}/scan.json"
            _, url = r2_upload_file(key, scan_file.read_bytes(), content_type="application/json")
            r2_results["cyber_scan"] = url
            if manifest.cyber.get("status") == "success":
                local_download_url = manifest.cyber.get("download_url")
                manifest.cyber["download_url"] = url
                manifest.cyber["download_source"] = "r2"
                manifest.cyber["fallback_download_url"] = local_download_url
        except Exception as exc:
            r2_results["cyber_scan_error"] = str(exc)

    # 4. Upload testcase artifacts so test results can load/download from R2.
    testcase_dir = get_submission_root(submission_id) / "artifacts" / "testcase"
    testcase_urls: dict[str, str] = {}
    if testcase_dir.exists():
        for filename, content_type in (
            ("test_suite.robot", "text/plain"),
            ("report.html", "text/html"),
            ("log.html", "text/html"),
            ("output.xml", "application/xml"),
        ):
            artifact_path = testcase_dir / filename
            if not artifact_path.exists():
                continue
            try:
                key = f"submissions/{submission_id}/testcase/{filename}"
                _, url = r2_upload_file(key, artifact_path.read_bytes(), content_type=content_type)
                testcase_urls[filename] = url
            except Exception as exc:
                r2_results[f"testcase_{filename}_error"] = str(exc)

    if testcase_urls and isinstance(manifest.testcase, dict):
        artifact_urls = manifest.testcase.get("artifact_urls")
        if not isinstance(artifact_urls, dict):
            artifact_urls = {}
        artifact_urls.update(testcase_urls)
        manifest.testcase["artifact_urls"] = artifact_urls
        manifest.testcase["artifact_source"] = "r2"
        if "log.html" in testcase_urls:
            manifest.testcase["log_url"] = testcase_urls["log.html"]
        if "output.xml" in testcase_urls:
            manifest.testcase["output_url"] = testcase_urls["output.xml"]
        if "report.html" in testcase_urls:
            manifest.testcase["report_url"] = testcase_urls["report.html"]

    manifest.r2_artifacts = r2_results
    if manifest.cyber:
        _persist_project_results(manifest.project_db_id, cybersecurity_result=manifest.cyber)
    if manifest.testcase:
        _persist_project_results(manifest.project_db_id, testcase_result=manifest.testcase)
    write_manifest(manifest)


def _materialize_deployment_project(submission_id: str) -> Path:
    source_dir = get_source_dir(submission_id)
    project_dir = Path(settings.projects_dir) / submission_id
    shutil.rmtree(project_dir, ignore_errors=True)
    shutil.copytree(source_dir, project_dir)
    return project_dir


async def _load_testcase_suite_content(testcase_url: str) -> str:
    if R2_PUBLIC_URL and testcase_url.startswith(R2_PUBLIC_URL.rstrip("/") + "/"):
        key = testcase_url.replace(R2_PUBLIC_URL.rstrip("/") + "/", "", 1)
        return get_file_bytes(key).decode("utf-8")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(testcase_url)
        response.raise_for_status()
        return response.text


def get_submission_manifest_service(submission_id: str, db: Session, current_user) -> SubmissionManifest:
    manifest = read_manifest(submission_id)
    _ensure_submission_access(manifest, db, current_user)
    set_artifact_download_urls(manifest)
    return manifest


def list_submission_artifacts_service(
    submission_id: str,
    db: Session,
    current_user,
) -> SubmissionArtifactListResponse:
    manifest = read_manifest(submission_id)
    _ensure_submission_access(manifest, db, current_user)
    set_artifact_download_urls(manifest)
    return SubmissionArtifactListResponse(
        submission_id=submission_id,
        artifacts=manifest.artifacts,
    )


def resolve_submission_artifact_service(
    submission_id: str,
    artifact_id: str,
    db: Session,
    current_user,
):
    from fastapi import HTTPException, status
    import json
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        manifest = read_manifest(submission_id)
        _ensure_submission_access(manifest, db, current_user)
        artifact, artifact_path = resolve_artifact_path(manifest, artifact_id)
        return artifact, artifact_path
    except FileNotFoundError as exc:
        # Fallback for Cybersecurity results if manifest is missing
        project = db.query(Project).filter(Project.submission_uuid == submission_id).first()
        if project and project.cybersecurity_result:
            try:
                cyber = project.cybersecurity_result
                if isinstance(cyber, str):
                    cyber = json.loads(cyber)
                
                if cyber.get("artifact_id") == artifact_id:
                    # Found matching cyber artifact in DB, check for file in results_dir
                    path = Path(settings.results_dir) / f"{submission_id}.json"
                    if path.exists():
                        from .manifest import ArtifactRecord
                        return ArtifactRecord(
                            artifact_id=artifact_id,
                            name="scan.json",
                            category="cyber",
                            relative_path=f"{submission_id}.json",
                            content_type="application/json"
                        ), path
            except Exception as inner_exc:
                logger.error(f"Fallback resolution error: {inner_exc}")

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Submission artifacts not found on server: {str(exc)}"
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error resolving artifact: {str(exc)}"
        ) from exc


async def activate_project_service(
    project_db_id: int,
    background_tasks: BackgroundTasks,
    db: Session,
    current_user,
):
    import logging
    from fastapi import HTTPException, status
    
    project = db.query(Project).filter(Project.id == project_db_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    
    if not project.container_resource:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no container resource")
        
    submission_id = f"proj-{project.id}"
    
    from app.deployment.api.submission_preview import _sessions, PreviewSession, _schedule_cleanup
    existing = _sessions.get(submission_id)
    
    if existing and existing.status == "running" and existing.seconds_remaining > 0:
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
            return {
                "status": "running",
                "preview_url": existing.preview_url,
                "seconds_remaining": existing.seconds_remaining,
            }
        else:
            logger = logging.getLogger(__name__)
            logger.info("Containers for %s stopped unexpectedly, forcing restart", submission_id)
            existing.status = "stopped"
            _sessions[submission_id] = existing
        
    if existing and existing.status == "starting":
        return {
            "status": "starting",
            "preview_url": None,
            "seconds_remaining": existing.seconds_remaining,
        }
        
    if existing and existing.status == "error":
        return {
            "status": "error",
            "error": existing.error,
        }
        
    original_compose_project = f"activate-{submission_id}"
    if project.container_resource:
        import re
        from app.utils.r2 import R2_PUBLIC_URL
        key = project.container_resource.replace(R2_PUBLIC_URL.rstrip('/') + "/", "")
        m = re.search(r"submissions/([^/]+)/", key)
        if m:
            original_compose_project = m.group(1)

    session = PreviewSession(
        submission_id=submission_id,
        compose_project=original_compose_project,
        runtime_dir=str(Path(settings.deployments_dir) / "activations" / submission_id),
    )
    _sessions[submission_id] = session
    
    def _do_activate():
        logger = logging.getLogger(__name__)
        try:
            logger.info(f"Activating project {project_db_id} from {project.container_resource}")
            
            from app.utils.r2 import R2_PUBLIC_URL, download_file_to_disk
            key = project.container_resource.replace(R2_PUBLIC_URL.rstrip('/') + "/", "")
            
            import shutil
            import uuid
            
            extract_dir = str(Path(settings.deployments_dir) / "activations" / "bundles" / str(uuid.uuid4()))
            Path(extract_dir).mkdir(parents=True, exist_ok=True)
            bundle_path = Path(extract_dir) / "bundle.tar.gz"
            
            # Use direct file download to avoid memory/timeout issues on large files
            download_file_to_disk(key, str(bundle_path))
                
            from app.deployment.services.docker.bundle_runner import run_from_bundle
            result = run_from_bundle(
                bundle_path=bundle_path,
                runtime_dir=Path(session.runtime_dir),
                compose_project=session.compose_project,
                remove_existing=True,
            )
            
            # Clean up temporary extracted folder
            shutil.rmtree(extract_dir, ignore_errors=True)
            
            session.status = "running"
            session.preview_url = f"/preview/{submission_id}/"
            session.service_ports = result.get("service_ports", [])
            _sessions[submission_id] = session
            
            from app.deployment.services.deployer.pipeline import deployment_store
            from app.deployment.models.deployment import DeploymentStatus, ServicePortMapping
            
            dep = deployment_store.get(submission_id)
            if not dep:
                dep = DeploymentStatus(deployment_id=submission_id, project_id=submission_id)
            dep.status = "running"
            dep.compose_project = session.compose_project
            if session.service_ports:
                dep.service_ports = [ServicePortMapping(**sp) for sp in session.service_ports]
                dep.compose_services = [sp.get("service") for sp in session.service_ports if sp.get("service")]
            dep.deploy_mode = "fullstack"

            # Build direct container URL from service_ports
            direct_url = None
            for sp in (session.service_ports or []):
                if not isinstance(sp, dict):
                    continue
                host_port = sp.get("host_port") or sp.get("hostPort")
                if host_port and sp.get("service") in ("frontend", "app", "web", "backend"):
                    from urllib.parse import urlparse as _urlparse
                    base = (settings.public_base_url or "http://localhost").rstrip("/")
                    _p = _urlparse(base)
                    # Removed HTTPS/ngrok check to allow direct port access
                    direct_url = f"{_p.scheme}://{_p.hostname}:{host_port}"
                    if sp.get("service") == "frontend":
                        break  # prefer frontend port

            if not direct_url and session.service_ports:
                sp = session.service_ports[0] if isinstance(session.service_ports[0], dict) else {}
                host_port = sp.get("host_port") or sp.get("hostPort")
                if host_port:
                    from urllib.parse import urlparse as _urlparse
                    base = (settings.public_base_url or "http://localhost").rstrip("/")
                    _p = _urlparse(base)
                    # Removed HTTPS/ngrok check
                    direct_url = f"{_p.scheme}://{_p.hostname}:{host_port}"

            session.preview_url = direct_url or f"/preview/{submission_id}/"
            dep.preview_url = session.preview_url
            _sessions[submission_id] = session
            deployment_store.save(dep)
            
            logger.info(f"Activated project {project_db_id} successfully → {session.preview_url}")
            
        except Exception as e:
            logger.exception(f"Activation error: {e}")
            session.status = "error"
            session.error = str(e)
            _sessions[submission_id] = session
            
        _schedule_cleanup(submission_id)
        
    background_tasks.add_task(_do_activate)
    return {
        "status": "starting",
        "preview_url": None,  # not ready yet — client should poll /preview/status
        "seconds_remaining": session.seconds_remaining,
    }
