from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.core.teacher.repository import get_teacher_by_user_id
from app.models.schema import Assignment, Attachment
from .dto import CreateAssignmentRequest, UpdateAssignmentRequest
from .repository import (
    get_classroom_by_id,
    get_project_type_by_id,
    get_language_by_id,
    get_assignments_by_classroom,
    get_assignment_by_id,
    update_assignment,
    soft_delete_assignment,
)


def create_assignment_service(
    db: Session,
    user_id: int,
    data: CreateAssignmentRequest,
    testcase_url: Optional[str],
    attachment_urls: List[str],
):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can create assignments")

    classroom = get_classroom_by_id(db, data.classroomId)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    if classroom.teacher_id != teacher.id:
        raise HTTPException(status_code=403, detail="You do not own this classroom")

    if not get_project_type_by_id(db, data.projecttypeId):
        raise HTTPException(status_code=404, detail="Project type not found")
    if not get_language_by_id(db, data.languageId):
        raise HTTPException(status_code=404, detail="Language not found")
    if data.startDate >= data.dueDate:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")

    assignment = Assignment(
        classroom_id=data.classroomId,
        title=data.name,
        description=data.detail,
        start_date=data.startDate,
        due_date=data.dueDate,
        is_group=data.isGroup,
        is_public=data.isPublic,
        project_type_id=data.projecttypeId,
        language_id=data.languageId,
        testcase_url=testcase_url,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    for url in attachment_urls:
        att = Attachment(assignment_id=assignment.id, file_url=url)
        db.add(att)
    db.commit()
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
    data: UpdateAssignmentRequest,
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

    if data.projecttypeId and not get_project_type_by_id(db, data.projecttypeId):
        raise HTTPException(status_code=404, detail="Project type not found")
    if data.languageId and not get_language_by_id(db, data.languageId):
        raise HTTPException(status_code=404, detail="Language not found")

    resolved_start = data.startDate or assignment.start_date
    resolved_due = data.dueDate or assignment.due_date
    if resolved_start >= resolved_due:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")

    update_data = {
        "title": data.name,
        "description": data.detail,
        "start_date": data.startDate,
        "due_date": data.dueDate,
        "is_group": data.isGroup,
        "is_public": data.isPublic,
        "project_type_id": data.projecttypeId,
        "language_id": data.languageId,
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