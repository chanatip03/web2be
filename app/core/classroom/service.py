from sqlalchemy.orm import Session
from app.core.classroom.dto import ClassroomUpdateDTO, CreateClassroomRequest
from app.core.user.repository import get_student_by_user_id, get_teacher_by_user_id
from app.models.schema import Classroom
from .repository import (
    create_classroom,
    get_classroom_by_id,
    get_classrooms_by_student_id,
    get_classrooms_by_teacher_id,
    is_classroom_of_teacher,
    update_classroom,
)
import random
import string

def generate_classroom_code() -> str:
    """สร้างรหัส classroom แบบสุ่ม 6 ตัวอักษร"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_new_classroom(data: CreateClassroomRequest, db: Session, current_user: dict):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can create classrooms")
    
    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise ValueError("Teacher profile not found")
    
    code = generate_classroom_code()

    classroom = Classroom(
        name=data.name,
        semester=data.semester,
        teacher_id=teacher.id,
        description=data.description,
        learningoutcomes=data.learningoutcomes,
        code=code,
    )

    create_classroom(db, classroom)

    return classroom


def get_classrooms_service(db: Session, current_user: dict):

    if current_user["role"] == "teacher":
        teacher = get_teacher_by_user_id(db, current_user["id"])
        if not teacher:
            return []
        classrooms = get_classrooms_by_teacher_id(db, teacher.id)

    elif current_user["role"] == "student":
        student = get_student_by_user_id(db, current_user["id"])
        if not student:
            return []
        classrooms = get_classrooms_by_student_id(db, student.id)

    else:
        return []

    return classrooms

def get_classroom_by_id_service(db: Session, classroom_id: int):

    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        return None

    return classroom

def update_classroom_service(db: Session, classroom_id: int,current_user: dict, payload: ClassroomUpdateDTO):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can update classrooms")
    
    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise ValueError("Teacher profile not found")

    classroom = is_classroom_of_teacher(db, classroom_id, teacher.id)
    if not classroom:
        raise ValueError("Classroom not found")
    
    update_data = {
        "name": payload.name,
        "semester": payload.semester,
        "description": payload.description,
        "learningoutcomes": payload.learningoutcomes
    }

    updated_classroom = update_classroom(db, classroom, update_data)

    return updated_classroom