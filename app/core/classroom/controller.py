from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from .service import get_syllabus_data, get_classroom_students, update_classroom_data
from .dto import SyllabusResponseDTO, ClassroomStudentsResponseDTO, ClassroomUpdateDTO
from app.utils.validator import get_current_teacher
from app.models.schema import Teacher

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.get("/{classroom_id}/syllabus", response_model=SyllabusResponseDTO)
def get_syllabus_endpoint(classroom_id: int, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    data = get_syllabus_data(db, classroom_id, teacher.user_id)

    if not data:
        raise HTTPException(status_code=404, detail="Classroom not found or access denied")

    return SyllabusResponseDTO(**data)


@router.put("/{classroom_id}")
def update_classroom_endpoint(
    classroom_id: int,
    payload: ClassroomUpdateDTO,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    success = update_classroom_data(db, classroom_id, teacher.user_id, payload)

    if not success:
        raise HTTPException(status_code=404, detail="Classroom not found or access denied")

    return {"message": "Classroom updated successfully"}
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db

from app.utils.validator import get_current_user
from .dto import (
    ClassroomMemberResponse,
    CreateClassroomRequest,
    ClassroomResponse,
)
from .service import (
    create_new_classroom,
    get_classrooms,
    join_classroom_by_code
)

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.post("/")
def create_classroom_endpoint(
    data: CreateClassroomRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
) -> ClassroomResponse:    
    try:
        classroom = create_new_classroom(data ,db ,current_user) 
        return ClassroomResponse.model_validate(classroom)
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

@router.get("/")
def get_classrooms_endpoint(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
) -> list[ClassroomResponse]:
    
    try:
        classrooms = get_classrooms(db, current_user)
        return [ClassroomResponse.model_validate(c) for c in classrooms]  
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch classrooms: {str(e)}"
        )

@router.post("/join/{classroom_id}")
def join_classroom_endpoint(
    classroom_id: int,
    code: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassroomMemberResponse:    
    try:
        result = join_classroom_by_code( db , current_user["id"] ,classroom_id , code)
        return ClassroomMemberResponse.model_validate(result)
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
