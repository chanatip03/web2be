from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.db.database import get_db
from .service import get_syllabus_data, get_classroom_students, update_classroom_data
from .dto import SyllabusResponseDTO, ClassroomStudentsResponseDTO, ClassroomUpdateDTO
from app.utils.validator import get_current_teacher
from app.models.schema import Teacher

router = APIRouter(prefix="/classroom", tags=["Classroom"])


@router.get("/{classroom_id}/students", response_model=ClassroomStudentsResponseDTO)
def get_students_endpoint(
    classroom_id: int,
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    data = get_classroom_students(db, classroom_id, teacher.user_id, search)

    if not data:
        raise HTTPException(status_code=404, detail="Classroom not found or access denied")

    return ClassroomStudentsResponseDTO(**data)
