from sqlalchemy.orm import Session
from app.models.schema import Student
from app.utils.notification import send_feedback_email, send_feedback_discord_dm
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


def send_feedback_notification_service(email: str, discord_user_id: str, feedback_text: str) -> dict:
    email_result = send_feedback_email(email, feedback_text)
    discord_result = send_feedback_discord_dm(discord_user_id, feedback_text)

    return {
        "email_sent": email_result["success"],
        "discord_sent": discord_result["success"],
        "email_error": email_result.get("error"),
        "discord_error": discord_result.get("error"),
    }