from sqlalchemy.orm import Session
from app.models.schema import Classroom, User, Teacher, ClassroomMember
from typing import List, Optional
import random
import string


def generate_classroom_code() -> str:
    """สร้างรหัส classroom แบบสุ่ม 8 ตัวอักษร"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


def create_classroom(
    db: Session, 
    name: str, 
    semester: str, 
    teacher_id: int,
    description: Optional[str] = None
) -> Classroom:
    """สร้าง classroom ใหม่"""
    # สร้างรหัส classroom ที่ไม่ซ้ำ
    code = generate_classroom_code()
    while db.query(Classroom).filter(Classroom.code == code).first():
        code = generate_classroom_code()
    
    classroom = Classroom(
        name=name,
        code=code,
        semester=semester,
        description=description,
        teacher_id=teacher_id
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


def get_classroom_by_id(db: Session, classroom_id: int) -> Optional[Classroom]:
    """ดึงข้อมูล classroom ด้วย ID (ยกเว้นที่ถูกลบ)"""
    return db.query(Classroom).filter(
        Classroom.id == classroom_id,
        Classroom.deleted_date.is_(None)
    ).first()


def get_classrooms_by_teacher(db: Session, teacher_id: int) -> List[Classroom]:
    """ดึง classroom ทั้งหมดของครู (ยกเว้นที่ถูกลบ)"""
    return db.query(Classroom).filter(
        Classroom.teacher_id == teacher_id,
        Classroom.deleted_date.is_(None)
    ).all()


def get_student_count(db: Session, classroom_id: int) -> int:
    """นับจำนวนนักเรียนใน classroom (ยกเว้นที่ถูกลบ)"""
    count = db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).count()
    return count