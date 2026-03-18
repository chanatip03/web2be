from sqlalchemy.orm import Session
from typing import Optional
from app.models.schema import Teacher
from .repository import (
    get_project_by_id,
    get_submission_of_by_project,
    get_classroom_by_project,
    update_project_score_feedback,
)


def _get_teacher_or_raise(db: Session, user_id: int) -> Teacher:
    teacher = db.query(Teacher).filter(Teacher.user_id == user_id).first()
    if not teacher:
        raise ValueError("User is not a teacher")
    return teacher


def _build_scorebook_response(project, student_user) -> dict:
    return {
        "project_id": project.id,
        "student": {
            "id": student_user.id,
            "first_name": student_user.first_name,
            "last_name": student_user.last_name,
            "image_url": student_user.image_url,
        },
        "score": project.score,
        "feedback": project.feedback,
    }


def get_scorebook_detail(db: Session, project_id: int, user_id: int) -> dict:
    """
    ดึงข้อมูล score และ feedback ของ project นี้
    ตรวจสอบว่าครูเป็นเจ้าของ classroom ของ assignment นี้
    """
    teacher = _get_teacher_or_raise(db, user_id)

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    classroom = get_classroom_by_project(db, project_id)
    if not classroom or classroom.teacher_id != teacher.id:
        raise PermissionError("Access denied: not your classroom")

    submission_of = get_submission_of_by_project(db, project_id)
    if not submission_of:
        raise ValueError("Submission owner not found")

    student_user = submission_of.student.user

    return _build_scorebook_response(project, student_user)


def save_scorebook(
    db: Session,
    project_id: int,
    user_id: int,
    score: Optional[int],
    feedback: Optional[str],
) -> dict:

    teacher = _get_teacher_or_raise(db, user_id)

    project = get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")

    classroom = get_classroom_by_project(db, project_id)
    if not classroom or classroom.teacher_id != teacher.id:
        raise PermissionError("Access denied: not your classroom")

    submission_of = get_submission_of_by_project(db, project_id)
    if not submission_of:
        raise ValueError("Submission owner not found")

    project = update_project_score_feedback(db, project, score, feedback)
    student_user = submission_of.student.user

    return _build_scorebook_response(project, student_user)