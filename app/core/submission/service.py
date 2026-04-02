from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.assignment.repository import get_assignment_by_id
from app.core.classroommember.repository import is_student_in_classroom
from app.core.security_scan.fs import validate_submission
from app.core.security_scan.normalizer import normalize_code_result
from app.core.security_scan.snyk_code import scan_source_code
from app.core.student.repository import get_student_by_user_id
from app.deployment.core.config import settings
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.models.project import FileNode, ProjectMetadata
from app.deployment.services.analyzer.file_scanner import build_file_tree
from app.deployment.services.deployer.pipeline import (
    deployment_store,
    project_store,
    run_deployment,
)
from app.testcase.services.runner import run_robot_tests_with_suite_content
from app.utils.r2 import R2_PUBLIC_URL, get_file_bytes

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


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_assignment_availability(assignment) -> None:
    if assignment.deleted_date is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    now = datetime.now(timezone.utc)
    start_date = _coerce_utc(getattr(assignment, "start_date", None))
    due_date = _coerce_utc(getattr(assignment, "due_date", None))

    if start_date and now < start_date:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment has not opened yet")
    if due_date and now > due_date:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assignment is already closed")


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

    _validate_assignment_availability(assignment)

    if not is_student_in_classroom(db, assignment.classroom_id, student.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student is not in the assignment classroom")

    submission_id = uuid.uuid4().hex
    execution_mode = _resolve_execution_mode(assignment)
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

    manifest = build_initial_manifest(
        submission_id=submission_id,
        assignment_id=assignment_id,
        submitted_by_user_id=current_user["id"],
        student_id=student.id,
        execution_mode=execution_mode,
        source_type=source_type,
        source_ref=source_ref,
        env=payload.env,
        testcase_source_url=assignment.testcase_url,
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
        status_url=f"/api/submission/{submission_id}",
        artifact_list_url=f"/api/submission/{submission_id}/artifacts",
    )


def _clone_repo_to_source(repo_url: str, source_dir: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(source_dir)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Git clone failed: {result.stderr or result.stdout}",
        )
    shutil.rmtree(source_dir / ".git", ignore_errors=True)


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
    except Exception as exc:
        manifest = read_manifest(submission_id)
        manifest.pipeline_status = "error"
        manifest.deployment = manifest.deployment or {}
        manifest.deployment.setdefault("message", "Submission pipeline stopped unexpectedly.")
        manifest.deployment["unexpected_error"] = str(exc)
        write_manifest(manifest)
        return

    manifest = read_manifest(submission_id)
    _update_pipeline_status(manifest)
    write_manifest(manifest)


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
        artifact = register_artifact(
            manifest,
            absolute_path=cyber_path,
            category="cyber",
            name="scan.json",
            content_type="application/json",
        )
        set_artifact_download_urls(manifest)
        manifest.cyber = {
            "status": "success",
            "languages": validation["languages"],
            "file_count": validation["file_count"],
            "issues_found": normalized.get("issues_found", 0),
            "artifact_id": artifact.artifact_id,
            "download_url": artifact.download_url,
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
    write_manifest(manifest)


async def _run_deployment_step(manifest: SubmissionManifest) -> None:
    manifest = _set_step_running(manifest, "deployment", mode=manifest.execution_mode)
    write_manifest(manifest)

    submission_id = manifest.submission_id
    project_id = submission_id
    deployment_id = submission_id
    project_name = _submission_source_name(manifest.source_ref, manifest.source_type)
    project_dir = _materialize_deployment_project(submission_id)

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
            project_name=project_name,
            status="analyzing",
            current_step=1,
            updated_at=datetime.now(),
        )
    )

    await run_deployment(deployment_id, project_id, manifest.execution_mode)
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
        error_message = deployment.error_message if deployment else "Deployment metadata not found"
        manifest.deployment = {
            "status": "error",
            "deployment_id": deployment_id,
            "project_id": project_id,
            "deploy_mode": manifest.execution_mode,
            "message": error_message,
            "artifacts": artifact_ids,
        }
        _set_step_finished(manifest, "deployment", "error", error=error_message or "Deployment failed")
        write_manifest(manifest)
        return

    manifest.deployment = {
        "status": "success",
        "deployment_id": deployment.deployment_id,
        "project_id": deployment.project_id,
        "deploy_mode": deployment.deploy_mode,
        "preview_url": deployment.preview_url or deployment.get_primary_url(),
        "api_url": deployment.api_url,
        "compose_services": deployment.compose_services,
        "service_ports": [sp.model_dump(mode="json") for sp in deployment.service_ports or []],
        "artifacts": artifact_ids,
    }
    _set_step_finished(
        manifest,
        "deployment",
        "success",
        preview_url=manifest.deployment.get("preview_url"),
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
        suite_content = suite_content.replace("http://localhost:3000", preview_url.rstrip("/"))

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

        set_artifact_download_urls(manifest)
        manifest.testcase = {
            "status": result.status,
            "run_id": result.test_id,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "artifacts": testcase_artifacts,
        }

        if result.status == "error":
            _set_step_finished(manifest, "testcase", "error", error=result.output[-500:])
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


def get_submission_manifest_service(submission_id: str) -> SubmissionManifest:
    manifest = read_manifest(submission_id)
    set_artifact_download_urls(manifest)
    return manifest


def list_submission_artifacts_service(submission_id: str) -> SubmissionArtifactListResponse:
    manifest = read_manifest(submission_id)
    set_artifact_download_urls(manifest)
    return SubmissionArtifactListResponse(
        submission_id=submission_id,
        artifacts=manifest.artifacts,
    )


def resolve_submission_artifact_service(submission_id: str, artifact_id: str):
    manifest = read_manifest(submission_id)
    artifact, artifact_path = resolve_artifact_path(manifest, artifact_id)
    return artifact, artifact_path