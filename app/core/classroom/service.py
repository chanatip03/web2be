from sqlalchemy.orm import Session
from typing import List, Optional
from app.models.schema import Classroom, User, Teacher
from .repository import (
    create_classroom,
    get_classroom_by_id,
    get_classrooms_by_teacher,
    get_student_count
)


def create_new_classroom(
    db: Session,
    user_id: int,
    name: str,
    semester: str,
    description: Optional[str] = None
) -> Classroom:
    """
    สร้าง classroom ใหม่
    เฉพาะครูเท่านั้นที่สร้างได้
    """
    # หา teacher_id จาก user_id
    teacher = db.query(Teacher).filter(Teacher.user_id == user_id).first()
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
    """
    ดึง classroom ทั้งหมดของครู
    """
    teacher = db.query(Teacher).filter(Teacher.user_id == user_id).first()
    if not teacher:
        return []
    
    return get_classrooms_by_teacher(db, teacher.id)


def get_classroom_details(db: Session, classroom_id: int, user_id: int) -> Optional[dict]:
    """
    ดึงรายละเอียด classroom
    ตรวจสอบว่าเป็นครูของ classroom นี้
    """
    classroom = get_classroom_by_id(db, classroom_id)
    if not classroom:
        return None
    
    # ตรวจสอบว่าเป็นครูของ classroom นี้
    teacher = db.query(Teacher).filter(Teacher.user_id == user_id).first()
    if not teacher or classroom.teacher_id != teacher.id:
        return None
    
    # สร้าง response พร้อมข้อมูลเพิ่มเติม
    teacher_user = db.query(User).filter(User.id == classroom.teacher.user_id).first()
    
    return {
        "id": classroom.id,
        "name": classroom.name,
        "code": classroom.code,
        "semester": classroom.semester,
        "description": classroom.description,
        "teacher_id": classroom.teacher_id,
        "teacher_name": f"{teacher_user.first_name} {teacher_user.last_name}",
        "student_count": get_student_count(db, classroom.id),
        "created_at": classroom.created_date
    }