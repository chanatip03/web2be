from sqlalchemy.orm import Session
from app.core.user.repository import get_student_by_user_id
from app.core.user.repository import get_teacher_by_user_id
from app.models.schema import ClassroomMember
from .repository import (
    add_student_to_classroom,
    get_classroon_member,
    is_student_in_classroom,
    delete_classroom_member,
    get_classrooms_by_code,
    get_classroom_member_by_id
)

from app.core.classroom.repository import (
    get_classroom_by_id,
    is_classroom_of_teacher,
    )

def join_classroom_by_code(db: Session, user_id: int, code: str):

    student = get_student_by_user_id(db, user_id)
    if not student:
        raise ValueError("User is not a student")

    classroom = get_classrooms_by_code(db, code)
    if not classroom:
        raise ValueError("Incorrect classroom code")

    if is_student_in_classroom(db, classroom.id, student.id):
        raise ValueError("Already joined this classroom")

    member = ClassroomMember(
        classroom_id=classroom.id,
        student_id=student.id
    )

    add_student_to_classroom(db, member)

    return get_classroom_member_by_id(db, member.id)

def get_classroom_member_service(db: Session, classroom_id: int):
    member = get_classroon_member(db, classroom_id)
    if not member:
        raise ValueError("Classroom member not found")

    return member

def delete_classroom_member_service(db: Session, classroom_id: int, student_id: int,current_user):
    if current_user["role"] != "teacher":
        raise ValueError("Only teachers can delete students from classroom")
    
    teacher = get_teacher_by_user_id(db, current_user["id"])
    if not teacher:
        raise ValueError("Teacher profile not found")

    classroom = is_classroom_of_teacher(db, classroom_id, teacher.id)
    if not classroom:
        raise ValueError("Classroom not found")
    
    if not is_student_in_classroom(db, classroom_id, student_id):
        raise ValueError("Student is not in the classroom")

    member = delete_classroom_member(db, classroom_id, student_id)
    return member