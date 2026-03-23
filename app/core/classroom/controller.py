from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.utils.validator import get_current_user
from .dto import (
    CreateClassroomRequest,
    ClassroomResponse,
    ClassroomUpdateDTO
)
from .service import (
    create_new_classroom,
    get_classroom_by_id_service,
    get_classrooms_service,
    update_classroom_service
)

router = APIRouter(prefix="/classroom", tags=["Classroom"])

@router.post("/", response_model=ClassroomResponse)
def create_classroom_endpoint(
    data: CreateClassroomRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):    
    try:
        classroom = create_new_classroom(data ,db ,current_user) 
        return classroom
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create classroom: {str(e)}"
        )

@router.get("/", response_model=list[ClassroomResponse])
def get_classrooms_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    
    try:
        classrooms = get_classrooms_service(db, current_user)
        return classrooms  
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch classrooms: {str(e)}"
        )

@router.get("/{classroom_id}",response_model=ClassroomResponse)
def get_classroom_by_id_endpoint(classroom_id: int, db: Annotated[Session, Depends(get_db)]):
    data = get_classroom_by_id_service(db, classroom_id)

    if not data:
        raise HTTPException(status_code=404, detail="Classroom not found or access denied")

    return data


@router.put("/{classroom_id}", response_model=ClassroomResponse)
def update_classroom_endpoint(
    classroom_id: int,
    payload: ClassroomUpdateDTO,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[Dict, Depends(get_current_user)],
):
    classroom = update_classroom_service(db, classroom_id, current_user, payload)

    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found or access denied")

    return classroom
