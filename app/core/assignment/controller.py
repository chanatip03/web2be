from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, status, UploadFile,Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.r2 import upload_file
from app.utils.validator import get_current_user
from .dto import (
    CreateAssignmentRequest,
    UpdateAssignmentRequest,
    AssignmentResponse,
)
from .service import (
    create_assignment_service,
    get_assignments_service,
    get_assignment_by_id_service,
    delete_assignment_service,
    update_assignment_testcase_service,
    get_assignment_testcase_content_service
)

router = APIRouter(prefix="/assignment", tags=["Assignment"])

@router.post("/", response_model=AssignmentResponse)
async def create_assignment(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
    data: Annotated[CreateAssignmentRequest, Depends(CreateAssignmentRequest.as_form)],
    testcase: Annotated[UploadFile | None, File()] = None,
    attachment: Annotated[List[UploadFile] | None, File()] = None,
    ):
    try:
        if testcase:
            file_bytes = await testcase.read()
            _, testcase_url = upload_file(
            f"testcase/{data.title}/{testcase.filename}",
            file_bytes,
            testcase.content_type
            )
        else:
            testcase_url = None
        
        attachment_urls = []
        for file in attachment or []:
            file_bytes = await file.read()
            _, url = upload_file(
                f"attachment/{data.title}/{file.filename}",
            file_bytes,
            file.content_type
            )
            attachment_urls.append(url)
        
        assignment = create_assignment_service(data, testcase_url, attachment_urls, db, current_user)
        
        return assignment
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create assignment: {str(e)}"
        )


@router.get("/", response_model=List[AssignmentResponse])
def get_assignments(
    classroom_id: int,
     db: Annotated[Session, Depends(get_db)],
):
    try:
        assignments = get_assignments_service(db, classroom_id)
        return assignments
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment_by_id(
    assignment_id: int,
     db: Annotated[Session, Depends(get_db)],
):
    try:
        assignment = get_assignment_by_id_service(db, assignment_id)
        return assignment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    assignment_id: int, 
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
    data: Annotated[UpdateAssignmentRequest, Depends(UpdateAssignmentRequest.as_form)],
    testcase: Annotated[UploadFile | None, File()] = None,
    attachment: Annotated[List[UploadFile], File()] = [], 
    ):
    try:
        testcase_url = None

        if testcase:
            file_bytes = await testcase.read()
            safe_title = data.title or "untitled"

            _, testcase_url = upload_file(
            f"testcase/{safe_title}/{testcase.filename}",
            file_bytes,
            testcase.content_type
        )
        
        attachment_urls = []
        for file in attachment:
            file_bytes = await file.read()
            _, url = upload_file(
                f"attachment/{data.title}/{file.filename}",
            file_bytes,
            file.content_type
            )
            attachment_urls.append(url)
        
        assignment = update_assignment_service(assignment_id,data, testcase_url, attachment_urls, db, current_user)
        
        return assignment
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update assignment: {str(e)}"
        )

@router.put("/{assignment_id}/testcase", response_model=AssignmentResponse)
async def update_assignment_testcase(
    assignment_id: int,
    content: Annotated[str, Form(...)],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
):
    try:
        assignment = update_assignment_testcase_service(assignment_id, content, db, current_user)
        return assignment
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update assignment testcase: {str(e)}"
        )

@router.get("/{assignment_id}/testcase", response_class=PlainTextResponse)
def get_assignment_testcase(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)]
):
    try:
        content = get_assignment_testcase_content_service(assignment_id, db)
        return content
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{assignment_id}", response_model=AssignmentResponse)
def delete_assignment(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
):
    try:
        assignment = delete_assignment_service(db, current_user, assignment_id)
        return assignment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    
# @router.get("/project_types")
# def get_project_types():