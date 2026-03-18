from sqlalchemy.orm import Session
from typing import Optional
from app.models.schema import Project, SubmissionOf


def get_project_by_id(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(
        Project.id == project_id,
        Project.deleted_date.is_(None)
    ).first()


def get_submission_of_by_project(db: Session, project_id: int) -> Optional[SubmissionOf]:
    return db.query(SubmissionOf).filter(
        SubmissionOf.project_id == project_id,
    ).first()