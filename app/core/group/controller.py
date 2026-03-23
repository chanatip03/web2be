from typing import Annotated, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.validator import get_current_user

from app.core.user.dto import StudentResponse

from .dto import (
    GroupResponse,
    CreateGroupRequest,
    UpdateGroupRequest
)
from .service import (
    create_group_service,
    get_group_members_service,
    get_available_member_service,
    update_group_service
)

router = APIRouter(prefix="/group", tags=["Group"])

@router.post("/", response_model=GroupResponse)
def create_group_endpoint(
    payload: CreateGroupRequest,
    current_user: Annotated[Dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        group = create_group_service(
            db,
            current_user["id"],
            payload.name,
            payload.assignment_id,
            payload.member_ids
        )
        return group
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{group_id}", response_model=GroupResponse)
def get_group_members_endpoint(
    group_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        members = get_group_members_service(db, group_id)
        return members
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/available/{assignment_id}", response_model=list[StudentResponse])
def get_available_member_endpoint(
    assignment_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        members = get_available_member_service(db, assignment_id)
        return members
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{group_id}", response_model=GroupResponse)
def update_group_endpoint(
    group_id: int,
    payload: UpdateGroupRequest,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        group = update_group_service(
            db,
            group_id,
            payload.name,
            payload.new_member_ids or [],
            payload.remove_member_ids or [],
        )
        return group
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))