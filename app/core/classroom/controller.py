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