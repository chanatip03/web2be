from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.validator import get_current_user

from .dto import (
    SubmissionAcceptedResponse,
    SubmissionArtifactListResponse,
    SubmissionCreateRequest,
)
from .manifest import SubmissionManifest
from .service import (
    create_submission_service,
    get_submission_manifest_service,
    list_submission_artifacts_service,
    resolve_submission_artifact_service,
)


router = APIRouter(prefix="/submission", tags=["Submission"])


@router.post("/{assignment_id}", response_model=SubmissionAcceptedResponse, status_code=202)
async def create_submission(
    assignment_id: int,
    background_tasks: BackgroundTasks,
    payload: SubmissionCreateRequest = Depends(SubmissionCreateRequest.as_form),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await create_submission_service(
        assignment_id=assignment_id,
        payload=payload,
        upload_file=file,
        background_tasks=background_tasks,
        db=db,
        current_user=current_user,
    )


@router.get("/{submission_id}", response_model=SubmissionManifest)
def get_submission_status(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return get_submission_manifest_service(submission_id, db, current_user)


@router.get("/{submission_id}/artifacts", response_model=SubmissionArtifactListResponse)
def list_submission_artifacts(
    submission_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return list_submission_artifacts_service(submission_id, db, current_user)


@router.get("/{submission_id}/artifacts/{artifact_id}")
def download_submission_artifact(
    submission_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    artifact, artifact_path = resolve_submission_artifact_service(submission_id, artifact_id, db, current_user)
    return FileResponse(
        path=artifact_path,
        media_type=artifact.content_type,
        filename=artifact.name,
    )