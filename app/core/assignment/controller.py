import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, status, UploadFile
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.r2 import upload_file
from app.utils.validator import get_current_user
from .dto import CreateAssignmentResponse, AssignmentListResponse, AttachmentResponse
from .service import create_assignment_service, get_assignments_service

router = APIRouter(prefix="/assignment", tags=["Assignment"])


@router.post("/", response_model=CreateAssignmentResponse)
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
        testcase_url: Optional[str] = None
        if testcase and testcase.filename:
            content = await testcase.read()
            ext = testcase.filename.split(".")[-1] if "." in testcase.filename else "bin"
            key = f"testcases/{uuid.uuid4()}.{ext}"
            _, testcase_url = upload_file(key, content, content_type=testcase.content_type)

        attachment_urls: List[str] = []
        if attachment:
            for file in attachment:
                if file and file.filename:
                    content = await file.read()
                    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
                    key = f"attachments/{uuid.uuid4()}.{ext}"
                    _, url = upload_file(key, content, content_type=file.content_type)
                    attachment_urls.append(url)

        assignment = create_assignment_service(
            db=db,
            user_id=current_user["id"],
            classroom_id=classroomId,
            title=name,
            description=detail,
            start_date=startDate,
            due_date=dueDate,
            is_group=isGroup,
            is_public=isPublic,
            project_type_id=projecttypeId,
            language_id=languageId,
            testcase_url=testcase_url,
            attachment_urls=attachment_urls,
        )

        return CreateAssignmentResponse(
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
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/", response_model=list[AssignmentListResponse])
def get_assignments(
    classroomId: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        assignments = get_assignments_service(db, current_user["id"], classroomId)
        return [
            AssignmentListResponse(
                id=a.id,
                name=a.title,
                detail=a.description,
                startDate=a.start_date,
                dueDate=a.due_date,
                isGroup=a.is_group,
                isPublic=a.is_public,
                projectType=a.project_type,
                language=a.language,
                testcaseUrl=a.testcase_url,
                attachments=[
                    AttachmentResponse(id=att.id, fileUrl=att.file_url)
                    for att in a.attachments
                ],
            )
            for a in assignments
        ]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))