from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactRecord(BaseModel):
    artifact_id: str
    name: str
    category: str
    relative_path: str
    content_type: str = "application/octet-stream"
    status: str = "ready"
    download_url: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)


class StepRecord(BaseModel):
    status: str = "queued"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class SubmissionManifest(BaseModel):
    submission_id: str
    assignment_id: int
    submitted_by_user_id: int
    student_id: int
    execution_mode: str
    source_type: str
    source_ref: Optional[str] = None
    env: Optional[str] = None
    testcase_source_url: Optional[str] = None
    pipeline_status: str = "queued"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    steps: Dict[str, StepRecord] = Field(default_factory=dict)
    deployment: Dict[str, Any] = Field(default_factory=dict)
    testcase: Dict[str, Any] = Field(default_factory=dict)
    cyber: Dict[str, Any] = Field(default_factory=dict)
    plagiarism: Dict[str, Any] = Field(default_factory=lambda: {"status": "not_requested"})
    artifacts: List[ArtifactRecord] = Field(default_factory=list)
    # R2 / DB persistence fields (populated during pipeline)
    source_r2_url: Optional[str] = None
    db_project_id: Optional[int] = None


def touch_manifest(manifest: SubmissionManifest) -> SubmissionManifest:
    manifest.updated_at = utc_now_iso()
    return manifest


def build_initial_manifest(
    *,
    submission_id: str,
    assignment_id: int,
    submitted_by_user_id: int,
    student_id: int,
    execution_mode: str,
    source_type: str,
    source_ref: Optional[str],
    env: Optional[str],
    testcase_source_url: Optional[str],
) -> SubmissionManifest:
    now = utc_now_iso()
    testcase_required = execution_mode in {"frontend-only", "backend-only"}
    testcase_ready = testcase_required and bool(testcase_source_url)

    testcase_status = "queued" if testcase_ready else "skipped"
    testcase_message = None
    if not testcase_required:
        testcase_message = "Execution mode does not require testcase."
    elif not testcase_source_url:
        testcase_message = "Assignment does not have a testcase file configured."

    return SubmissionManifest(
        submission_id=submission_id,
        assignment_id=assignment_id,
        submitted_by_user_id=submitted_by_user_id,
        student_id=student_id,
        execution_mode=execution_mode,
        source_type=source_type,
        source_ref=source_ref,
        env=env,
        testcase_source_url=testcase_source_url,
        pipeline_status="queued",
        created_at=now,
        updated_at=now,
        steps={
            "prepare": StepRecord(
                status="success",
                started_at=now,
                finished_at=now,
                details={"source_type": source_type},
            ),
            "cyber": StepRecord(status="queued"),
            "deployment": StepRecord(status="queued"),
            "testcase": StepRecord(
                status=testcase_status,
                details={"message": testcase_message} if testcase_message else {},
            ),
            "plagiarism": StepRecord(
                status="not_requested",
                details={"message": "Teacher-triggered flow only."},
            ),
        },
        deployment={"status": "queued"},
        testcase={
            "status": testcase_status,
            "message": testcase_message,
        },
        cyber={"status": "queued"},
        plagiarism={
            "status": "not_requested",
            "message": "Teacher-triggered flow only.",
        },
    )