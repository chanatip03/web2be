import csv
import io
from sqlalchemy.orm import Session
from app.core.classroom.dto import ClassroomResponse, CreateClassroomRequest , ClassroomMemberResponse
from app.core.student.repository import get_student_by_user_id
from app.core.teacher.repository import get_teacher_by_user_id
from app.models.schema import Classroom, ClassroomMember
from app.utils.r2 import upload_file
from .repository import (
    create_classroom,
    get_classroom_by_id,
    get_classrooms_by_student_id,
    get_classrooms_by_teacher_id,
    is_student_in_classroom,
    add_student_to_classroom
)
import random
import string


def generate_classroom_code() -> str:
    """สร้างรหัส classroom แบบสุ่ม 6 ตัวอักษร"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_new_classroom(data: CreateClassroomRequest, db: Session, current_user):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can create classrooms")
    
    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise ValueError("Teacher profile not found")
    
    code = generate_classroom_code()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["student_id", "name"])

    csv_bytes = output.getvalue().encode("utf-8")

    safe_semester = data.semester.replace("/", "-")
    filename = f"{data.name}_{safe_semester}_scores.csv"
    key = f"classrooms/{filename}"

    _, url = upload_file(
        key,
        csv_bytes,
        "text/csv"
    )

    classroom = Classroom(
        name=data.name,
        semester=data.semester,
        teacher_id=teacher.id,
        description=data.description,
        learning_out_come=data.learning_out_come,
        code=code,
        excel_link=url
    )

    create_classroom(db, classroom)

    return classroom


def get_classrooms(db: Session, current_user):

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

def join_classroom_by_code(db: Session, user_id: int, classroom_id: int, code: str):

    student = get_student_by_user_id(db, user_id)
    if not student:
        raise ValueError("User is not a student")
    if is_student_in_classroom(db, classroom_id, student.id):
        raise ValueError("Already joined this classroom")

    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        raise ValueError("Classroom not found")

    if classroom.code != code:
        raise ValueError("Incorrect classroom code")
    
    member = ClassroomMember(
        classroom_id=classroom_id,
        student_id=student.id
    )

    add_student_to_classroom(db, member)

    return member