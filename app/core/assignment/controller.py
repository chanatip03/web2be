import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, status, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.r2 import upload_file
from app.utils.validator import get_current_user
from .dto import (
    CreateAssignmentRequest,
    UpdateAssignmentRequest,
    AssignmentResponse,
    AttachmentResponse,
    DeleteAssignmentResponse,
)
from .service import (
    create_assignment_service,
    get_assignments_service,
    get_assignment_by_id_service,
    update_assignment_service,
    delete_assignment_service,
)

router = APIRouter(prefix="/assignment", tags=["Assignment"])


def _build_response(assignment) -> AssignmentResponse:
    return AssignmentResponse(
        id=assignment.id,
        name=assignment.title,
        detail=assignment.description,
        startDate=assignment.start_date,
        dueDate=assignment.due_date,
        isGroup=assignment.is_group,
        isPublic=assignment.is_public,
        projectType=assignment.project_type,
        language=assignment.language,
        testcaseUrl=assignment.testcase_url,
        attachments=[
            AttachmentResponse(id=a.id, fileUrl=a.file_url)
            for a in assignment.attachments
        ],
    )


async def _upload_testcase(testcase: Optional[UploadFile]) -> Optional[str]:
    if testcase and testcase.filename:
        content = await testcase.read()
        ext = testcase.filename.split(".")[-1] if "." in testcase.filename else "bin"
        key = f"testcases/{uuid.uuid4()}.{ext}"
        _, url = upload_file(key, content, content_type=testcase.content_type)
        return url
    return None


async def _upload_attachments(attachment: Optional[List[UploadFile]]) -> List[str]:
    urls = []
    if attachment:
        for file in attachment:
            if file and file.filename:
                content = await file.read()
                ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
                key = f"attachments/{uuid.uuid4()}.{ext}"
                _, url = upload_file(key, content, content_type=file.content_type)
                urls.append(url)
    return urls


@router.post("/", response_model=AssignmentResponse)
async def create_assignment(
    name: Optional[str] = Form(None),
    detail: Optional[str] = Form(None),
    startDate: Optional[datetime] = Form(None),
    dueDate: Optional[datetime] = Form(None),
    isGroup: bool = Form(False),
    isPublic: bool = Form(False),
    projecttypeId: Optional[int] = Form(None),
    languageId: Optional[int] = Form(None),
    classroomId: Optional[int] = Form(None),
    testcase: Optional[UploadFile] = File(None),
    attachment: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = CreateAssignmentRequest(
            name=name, detail=detail, startDate=startDate, dueDate=dueDate,
            isGroup=isGroup, isPublic=isPublic, projecttypeId=projecttypeId,
            languageId=languageId, classroomId=classroomId,
        )
        testcase_url = await _upload_testcase(testcase)
        attachment_urls = await _upload_attachments(attachment)
        assignment = create_assignment_service(db, current_user["id"], data, testcase_url, attachment_urls)
        return _build_response(assignment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/", response_model=List[AssignmentResponse])
def get_assignments(
    classroomId: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        assignments = get_assignments_service(db, current_user["id"], classroomId)
        return [_build_response(a) for a in assignments]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment_by_id(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        assignment = get_assignment_by_id_service(db, current_user["id"], assignment_id)
        return _build_response(assignment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    assignment_id: int,
    name: Optional[str] = Form(None),
    detail: Optional[str] = Form(None),
    startDate: Optional[datetime] = Form(None),
    dueDate: Optional[datetime] = Form(None),
    isGroup: Optional[bool] = Form(None),
    isPublic: Optional[bool] = Form(None),
    projecttypeId: Optional[int] = Form(None),
    languageId: Optional[int] = Form(None),
    testcase: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        data = UpdateAssignmentRequest(
            name=name, detail=detail, startDate=startDate, dueDate=dueDate,
            isGroup=isGroup, isPublic=isPublic, projecttypeId=projecttypeId,
            languageId=languageId,
        )
        testcase_url = await _upload_testcase(testcase)
        assignment = update_assignment_service(db, current_user["id"], assignment_id, data, testcase_url)
        return _build_response(assignment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/{assignment_id}", response_model=DeleteAssignmentResponse)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        delete_assignment_service(db, current_user["id"], assignment_id)
        return DeleteAssignmentResponse(message="Assignment deleted successfully")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))