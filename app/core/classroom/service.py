from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.schema import Classroom, User, Teacher
from .repository import (
    create_classroom,
    get_classroom_by_id,
    get_classroom_by_code,
    get_classrooms_by_teacher,
    get_student_count,
    get_classroom_members,
    get_user_by_id,
    get_teacher_by_user_id,
    get_student_by_user_id,
    is_student_in_classroom,
    add_student_to_classroom
)


def create_new_classroom(
    db: Session,
    user_id: int,
    name: str,
    semester: str,
    description: Optional[str] = None
) -> Classroom:
    """สร้าง classroom ใหม่ (เฉพาะครู)"""
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        raise ValueError("User is not a teacher")
    
    classroom = create_classroom(
        db=db,
        name=name,
        semester=semester,
        teacher_id=teacher.id,
        description=description
    )
    
    return classroom


def get_teacher_classrooms(db: Session, user_id: int) -> List[Classroom]:
    """ดึง classroom ทั้งหมดของครู"""
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher:
        return []
    
    return get_classrooms_by_teacher(db, teacher.id)


def get_classroom_details(db: Session, classroom_id: int, user_id: int) -> Optional[dict]:
    """ดึงรายละเอียด classroom (เฉพาะครูของ classroom)"""
    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        return None
    
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher or classroom.teacher_id != teacher.id:
        return None
    
    teacher_user = get_user_by_id(db, teacher.user_id)
    
    return {
        "id": classroom.id,
        "name": classroom.name,
        "code": classroom.code,
        "semester": classroom.semester,
        "description": classroom.description,
        "teacher_id": classroom.teacher_id,
        "teacher_name": f"{teacher_user.first_name} {teacher_user.last_name}" if teacher_user else "Unknown",
        "student_count": get_student_count(db, classroom.id),
        "created_at": classroom.created_date
    }


def get_classroom_students_for_export(db: Session, classroom_id: int, user_id: int) -> Optional[List[dict]]:
    """ดึงข้อมูลนักเรียนสำหรับ export CSV"""
    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        return None
    
    teacher = get_teacher_by_user_id(db, user_id)
    if not teacher or classroom.teacher_id != teacher.id:
        return None
    
    return get_classroom_members(db, classroom_id)


def join_classroom_by_code(db: Session, user_id: int, code: str) -> dict:
    """นักเรียนเข้าร่วม classroom ด้วย code"""
    classroom = get_classroom_by_code(db, code)
    if not classroom:
        raise ValueError("Classroom not found")
    
    student = get_student_by_user_id(db, user_id)
    if not student:
        raise ValueError("User is not a student")
    
    if is_student_in_classroom(db, classroom.id, student.id):
        raise ValueError("Already joined this classroom")
    
    member = add_student_to_classroom(db, classroom.id, student.id)
    
    return {
        "message": "Joined classroom successfully",
        "classroom_id": classroom.id,
        "classroom_name": classroom.name,
        "joined_at": member.created_date
    }