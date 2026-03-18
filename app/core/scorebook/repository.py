from sqlalchemy.orm import Session
from typing import Optional
from app.models.schema import Project, SubmissionOf, Assignment, Classroom


def get_project_by_id(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(
        Project.id == project_id,
        Project.deleted_date.is_(None)
    ).first()


def get_submission_of_by_project(db: Session, project_id: int) -> Optional[SubmissionOf]:
    return db.query(SubmissionOf).filter(
        SubmissionOf.project_id == project_id,
    ).first()


def get_classroom_by_project(db: Session, project_id: int) -> Optional[Classroom]:
    result = (
        db.query(Classroom)
        .join(Assignment, Assignment.classroom_id == Classroom.id)
        .join(Project, Project.assignment_id == Assignment.id)
        .filter(
            Project.id == project_id,
            Project.deleted_date.is_(None),
            Classroom.deleted_date.is_(None),
        )
        .first()
    )
    return result


def update_project_score_feedback(
    db: Session,
    project: Project,
    score: Optional[int],
    feedback: Optional[str],
) -> Project:
    """อัปเดต score และ feedback ใน project"""
    project.score = score
    project.feedback = feedback
    db.commit()
    db.refresh(project)
    return project