from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.core.teacher.repository import get_teacher_by_user_id
from .repository import (
    get_classroom_by_id,
    get_project_type_by_id,
    get_language_by_id,
    get_assignments_by_classroom,
    get_assignment_by_id,
    create_assignment,
    create_attachment,
    update_assignment,
    soft_delete_assignment,
)


def create_assignment_service(
    db: Session,
    user_id: int,
    classroom_id: int,
    title: str,
    description: Optional[str],
    start_date: datetime,
    due_date: datetime,
    is_group: bool,
    is_public: bool,
    project_type_id: int,
    language_id: int,
    testcase_url: Optional[str],
    attachment_urls: List[str],
):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can create assignments")

    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this classroom")

    if not get_project_type_by_id(db, project_type_id):
        raise HTTPException(status_code=404, detail="Project type not found")
    if not get_language_by_id(db, language_id):
        raise HTTPException(status_code=404, detail="Language not found")
    if start_date >= due_date:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")

    assignment = create_assignment(
        db=db,
        classroom_id=classroom_id,
        title=title,
        description=description,
        start_date=start_date,
        due_date=due_date,
        is_group=is_group,
        is_public=is_public,
        project_type_id=project_type_id,
        language_id=language_id,
        testcase_url=testcase_url,
    )

    for url in attachment_urls:
        create_attachment(db, assignment.id, url)

    db.refresh(assignment)
    return assignment


def get_assignments_service(db: Session, user_id: int, classroom_id: int):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can view assignments")

    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this classroom")

    return get_assignments_by_classroom(db, classroom_id)


def get_assignment_by_id_service(db: Session, user_id: int, assignment_id: int):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can view assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    classroom = get_classroom_by_id(db, assignment.classroom_id)
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this assignment")

    return assignment


def update_assignment_service(
    db: Session,
    user_id: int,
    assignment_id: int,
    title: Optional[str],
    description: Optional[str],
    start_date: Optional[datetime],
    due_date: Optional[datetime],
    is_group: Optional[bool],
    is_public: Optional[bool],
    project_type_id: Optional[int],
    language_id: Optional[int],
    testcase_url: Optional[str],
):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can update assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    classroom = get_classroom_by_id(db, assignment.classroom_id)
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this assignment")

    if project_type_id and not get_project_type_by_id(db, project_type_id):
        raise HTTPException(status_code=404, detail="Project type not found")
    if language_id and not get_language_by_id(db, language_id):
        raise HTTPException(status_code=404, detail="Language not found")

    resolved_start = start_date or assignment.start_date
    resolved_due = due_date or assignment.due_date
    if resolved_start >= resolved_due:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")

    update_data = {
        "title": title,
        "description": description,
        "start_date": start_date,
        "due_date": due_date,
        "is_group": is_group,
        "is_public": is_public,
        "project_type_id": project_type_id,
        "language_id": language_id,
        "testcase_url": testcase_url,
    }

    return update_assignment(db, assignment, update_data)


def delete_assignment_service(db: Session, user_id: int, assignment_id: int):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can delete assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    classroom = get_classroom_by_id(db, assignment.classroom_id)
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this assignment")

    soft_delete_assignment(db, assignment)