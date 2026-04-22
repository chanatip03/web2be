from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.utils.validator import get_current_user
from .dto import (
    ClassroomMemberResponse,
)
from .service import (
    delete_classroom_member_service,
    join_classroom_by_code,
    get_classroom_member_service,
)

router = APIRouter(prefix="/classroommember", tags=["ClassroomMember"])

@router.post("/", response_model=ClassroomMemberResponse)
def join_classroom_endpoint(
    code: str,
    current_user: Annotated[Dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):    
    try:
        result = join_classroom_by_code( db , current_user["id"] , code)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to join classroom: {str(e)}"
        )
    
@router.get("/{classroom_id}", response_model=list[ClassroomMemberResponse])
def get_classroom_member(
    classroom_id: int,
    db: Annotated[Session, Depends(get_db)],
):    
    try:
        member = get_classroom_member_service( db, classroom_id)
        return member
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch classroom member: {str(e)}"
        )
    
@router.delete("/{classroom_id}", response_model=ClassroomMemberResponse)
def delete_classroom_member(
    classroom_id: int,
    student_id:int,
    current_user: Annotated[Dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):    
    try:
        member = delete_classroom_member_service( db, classroom_id, student_id, current_user)
        return ClassroomMemberResponse.model_validate(member)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch classroom member: {str(e)}"
        )