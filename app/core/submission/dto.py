from __future__ import annotations

from typing import Optional

from fastapi import Form
from pydantic import BaseModel, Field

from .manifest import ArtifactRecord


class SubmissionCreateRequest(BaseModel):
    repo_url: Optional[str] = None
    env: Optional[str] = None
    group_id: Optional[int] = None
    # Optional override sent by frontend:
    # frontend-only | backend-only | fullstack (also accepts aliases like "frontend", "backend", "full")
    project_type: Optional[str] = Field(default=None, validation_alias="projectType")
    # Backwards/alternate name used by some clients
    deploy_mode: Optional[str] = None

    @classmethod
    def as_form(
        cls,
        repo_url: Optional[str] = Form(None),
        env: Optional[str] = Form(None),
        group_id: Optional[int] = Form(None),
        project_type: Optional[str] = Form(None, alias="projectType"),
        deploy_mode: Optional[str] = Form(None),
    ):
        return cls(
            repo_url=repo_url,
            env=env,
            group_id=group_id,
            project_type=project_type,
            deploy_mode=deploy_mode,
        )


class SubmissionAcceptedResponse(BaseModel):
    submission_id: str
    assignment_id: int
    execution_mode: str
    pipeline_status: str
    is_late: bool = False
    status_url: str
    artifact_list_url: str

    class Config:
        from_attributes = True


class SubmissionArtifactListResponse(BaseModel):
    submission_id: str
    artifacts: list[ArtifactRecord]

    class Config:
        from_attributes = True
