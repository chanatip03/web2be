import logging
from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, status, UploadFile, Form
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
    update_assignment_service,
    delete_assignment_service,
    update_assignment_testcase_service,
    get_assignment_testcase_content_service
)
from app.core.generatetestcase.services.generator import generate_robot_suite_content
import re

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assignment", tags=["Assignment"])



def safe_path(text: str):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)


@router.post("", response_model=AssignmentResponse)
@router.post("/", response_model=AssignmentResponse)
async def create_assignment(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
    data: Annotated[CreateAssignmentRequest, Depends(CreateAssignmentRequest.as_form)],
    testcase: Annotated[UploadFile | None, File()] = None,
    attachment: Annotated[List[UploadFile] | None, File()] = None,
):
    try:
        safe_title = safe_path(data.title or "untitled")

        # ── Upload testcase ──
        testcase_url = None
        if testcase:
            file_bytes = await testcase.read()
            _, testcase_url = upload_file(
                f"testcase/{safe_title}/{testcase.filename}",
                file_bytes,
                testcase.content_type
            )

        # ── Upload attachments ──
        attachment_urls = []
        if attachment:
            for file in attachment:
                file_bytes = await file.read()
                _, url = upload_file(
                    f"attachment/{safe_title}/{file.filename}",
                    file_bytes,
                    file.content_type
                )
                attachment_urls.append(url)

        # ── Create assignment ──
        assignment = create_assignment_service(
            data, testcase_url, attachment_urls, db, current_user
        )

        # ── Auto-generate testcase ──
        if not testcase_url:
            try:
                prompt = f"Assignment title: {data.title}"
                if data.description:
                    prompt += f"\nAssignment description: {data.description}"
                prompt += "\nGenerate Robot Framework testcases."

                context_id = f"assignment-{assignment.id}"

                suite_content = await generate_robot_suite_content(
                    context_id=context_id,
                    user_prompt=prompt,
                )

                assignment = update_assignment_testcase_service(
                    assignment.id, suite_content, db, current_user
                )

            except Exception as gen_err:
                logger.warning(
                    "Auto-generate testcase failed for assignment %s: %s",
                    assignment.id,
                    gen_err,
                )

        return assignment

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to create assignment"
        )

@router.get("/classroom/{classroom_id}", response_model=List[AssignmentResponse])
def get_assignments(
    classroom_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
):
    try:
        assignments = get_assignments_service(db, classroom_id, current_user)
        return assignments
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/detail/{assignment_id}", response_model=AssignmentResponse)
def get_assignment_by_id(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
):
    try:
        return get_assignment_by_id_service(db, assignment_id)

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{assignment_id}", response_model=AssignmentResponse)
async def update_assignment(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
    data: Annotated[UpdateAssignmentRequest, Depends(UpdateAssignmentRequest.as_form)],
    testcase: Annotated[UploadFile | None, File()] = None,
    attachment: Annotated[List[UploadFile] | None, File()] = None,
):
    try:
        safe_title = safe_path(data.title or "untitled")

        testcase_url = None
        if testcase:
            file_bytes = await testcase.read()
            _, testcase_url = upload_file(
                f"testcase/{safe_title}/{testcase.filename}",
                file_bytes,
                testcase.content_type
            )

        attachment_urls = []
        if attachment:
            for file in attachment:
                file_bytes = await file.read()
                _, url = upload_file(
                    f"attachment/{safe_title}/{file.filename}",
                    file_bytes,
                    file.content_type
                )
                attachment_urls.append(url)

        return update_assignment_service(
            assignment_id,
            data,
            testcase_url,
            attachment_urls,
            db,
            current_user
        )

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update assignment")

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
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Failed to update assignment testcase"
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
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete assignment")
    
# @router.get("/project_types")
# def get_project_types():
