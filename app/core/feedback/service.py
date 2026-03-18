from sqlalchemy.orm import Session
from app.models.schema import Student
from .repository import get_project_by_id, get_submission_of_by_project


def _get_student_or_raise(db: Session, user_id: int) -> Student:
    student = db.query(Student).filter(Student.user_id == user_id).first()
    if not student:
        raise ValueError("User is not a student")
    return student


def get_feedback_detail(db: Session, project_id: int, user_id: int) -> dict:
    student = _get_student_or_raise(db, user_id)

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    submission_of = get_submission_of_by_project(db, project_id)
    if not submission_of or submission_of.student_id != student.id:
        raise PermissionError("Access denied: not your project")

    return {
        "project_id": project.id,
        "score": project.score,
        "feedback": project.feedback,
    }