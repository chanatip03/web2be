from typing import List, Optional
from datetime import timezone
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException

from app.core.user.repository import get_teacher_by_user_id
from app.models.schema import Assignment, Attachment
from app.utils.r2 import delete_file, upload_file, get_file_bytes
import io
import zipfile
from .dto import CreateAssignmentRequest, UpdateAssignmentRequest
from .repository import (
    create_assignment,
    create_attachment,
    delete_attachment_by_id,
    get_assignments_by_classroom,
    get_assignment_by_id,
    get_attachment_by_id,
    soft_delete_assignment,
    update_assignment,
)

from app.core.classroom.repository import (
    get_classroom_by_id,
    is_classroom_of_teacher
)

def create_assignment_service(
    data: CreateAssignmentRequest,
    testcase_url: Optional[str],
    attachment_urls: List[str],
    db: Session,
    current_user,
):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can update classrooms")
    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can create assignments")
    classroom = get_classroom_by_id(db, data.classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")
    owner = is_classroom_of_teacher(db, data.classroom_id, teacher.id)
    if not owner:
        raise ValueError("Classroom is not under  your control")
    if data.due_date and data.start_date >= data.due_date:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")
    
    assignment = Assignment(
        title=data.title,
        description=data.description,
        start_date=data.start_date.astimezone(timezone.utc),
        due_date=data.due_date.astimezone(timezone.utc),
        is_group=data.is_group,
        project_type_id=data.project_type_id,
        language_id=data.language_id,
        classroom_id=data.classroom_id,
        testcase_url=testcase_url,
    )

    create_assignment(db, assignment)

    attachments = [
        Attachment(file_url=url, assignment_id=assignment.id)
        for url in attachment_urls
    ]
    
    create_attachment(db,attachments)
    
    assignment = get_assignment_by_id(db , assignment.id)

    return assignment


def get_assignments_service(db: Session, classroom_id: int):
    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    return get_assignments_by_classroom(db, classroom_id)

def get_assignment_by_id_service(db: Session, assignment_id: int):
    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return assignment


def update_assignment_service(
    assignment_id: int,
    data: UpdateAssignmentRequest,
    testcase_url: Optional[str],
    attachment_urls: List[str],
    db: Session,
    current_user,
):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can update classrooms")

    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can update assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    owner = is_classroom_of_teacher(db, assignment.classroom_id, teacher.id)
    if not owner:
        raise ValueError("Not your classroom")

    if data.start_date and data.due_date and data.start_date >= data.due_date:
        raise HTTPException(status_code=422, detail="startDate must be before dueDate")

    if data.delete_testcase_url and assignment.testcase_url:
        delete_file(assignment.testcase_url)
        assignment.testcase_url = None

    if data.delete_attachment_ids:
        for att_id in data.delete_attachment_ids:
            attachment = get_attachment_by_id(db, att_id)

            if not attachment:
                continue

            if attachment.assignment_id != assignment_id:
                continue

            delete_file(attachment.file_url)
            delete_attachment_by_id(db, attachment)

    if attachment_urls:
        attachments = [
            Attachment(file_url=url, assignment_id=assignment_id)
            for url in attachment_urls
        ]
        create_attachment(db, attachments)

    if testcase_url:
        assignment.testcase_url = testcase_url

    update_data = data.model_dump(exclude_unset=True, exclude={"classroom_id", "delete_attachment_ids", "delete_testcase_url"})

    update_assignment(db, assignment, update_data)

    return assignment

def update_assignment_testcase_service(
    assignment_id: int,
    content: str,
    db: Session,
    current_user,
):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can update assignments")

    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can update assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    owner = is_classroom_of_teacher(db, assignment.classroom_id, teacher.id)
    if not owner:
        raise ValueError("Not your classroom")

    file_bytes = content.encode("utf-8")

    if assignment.testcase_url:
        try:
            delete_file(assignment.testcase_url)
        except Exception:
            pass
            
    safe_title = assignment.title or "untitled"
    _, testcase_url = upload_file(
        f"testcase/{safe_title}/testcase.robot",
        file_bytes,
        "text/plain"
    )

    assignment.testcase_url = testcase_url
    db.commit()
    db.refresh(assignment)

    return assignment

def get_assignment_testcase_content_service(assignment_id: int, db: Session):
    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment or not assignment.testcase_url:
        raise HTTPException(status_code=404, detail="Testcase not found")
        
    import os
    r2_public_url = os.getenv("R2_PUBLIC_URL", "")
    key = assignment.testcase_url.replace(r2_public_url.rstrip("/") + "/", "")
    
    try:
        file_bytes = get_file_bytes(key)
        if key.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                first_name = zf.namelist()[0]
                content = zf.read(first_name).decode("utf-8")
        else:
            content = file_bytes.decode("utf-8")
        return content
    except Exception as e:
        raise ValueError(f"Failed to fetch testcase from R2: {str(e)}")

def delete_assignment_service(db: Session, current_user, assignment_id: int):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can update classrooms")

    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise HTTPException(status_code=403, detail="Only teachers can update assignments")

    assignment = get_assignment_by_id(db, assignment_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    owner = is_classroom_of_teacher(db, assignment.classroom_id, teacher.id)
    if not owner:
        raise ValueError("Not your classroom")

    assignment = soft_delete_assignment(db, assignment)
    
    return assignment