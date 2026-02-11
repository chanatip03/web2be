from sqlalchemy.orm import Session
from .repository import (get_classroom_for_syllabus, get_classroom_if_teacher, get_students_query, 
                         count_students, get_classroom_if_teacher, get_teacher_by_user_id, get_classroom_for_syllabus)
from app.models.schema import LearningOutcome

def get_syllabus_data(db: Session, classroom_id: int, user_id: int):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return None

    classroom = get_classroom_for_syllabus(db, classroom_id, teacher.id)
    if not classroom:
        return None

    teacher_name = f"{classroom.teacher.user.first_name} {classroom.teacher.user.last_name}"

    return {
        "classroom_name": classroom.name,
        "teacher_name": teacher_name,
        "classroom_description": classroom.description,
        "learning_outcomes": classroom.learning_outcomes
    }

def update_classroom_data(db: Session, classroom_id: int, user_id: int, payload):
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return False

    classroom = get_classroom_if_teacher(db, classroom_id, teacher.id)
    if not classroom:
        return False

    if payload.name is not None:
        classroom.name = payload.name

    if payload.description is not None:
        classroom.description = payload.description

    if payload.learning_outcomes is not None:
        keep_ids = []

        for lo in payload.learning_outcomes:
            if lo.id:
                existing = next((x for x in classroom.learning_outcomes if x.id == lo.id), None)
                if existing:
                    existing.description = lo.description
                    keep_ids.append(existing.id)
            else:
                new_lo = LearningOutcome(classroom_id=classroom.id, description=lo.description)
                db.add(new_lo)

        for old_lo in classroom.learning_outcomes:
            if old_lo.id not in keep_ids:
                db.delete(old_lo)

    db.commit()
    return True
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
