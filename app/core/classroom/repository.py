from sqlalchemy.orm import Session
from app.models.schema import Classroom, User, Teacher, ClassroomMember, Student
from typing import List, Optional
import random
import string


def generate_classroom_code() -> str:
    """สร้างรหัส classroom แบบสุ่ม 6 ตัวอักษร"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def create_classroom(
    db: Session, 
    name: str, 
    semester: str, 
    teacher_id: int,
    description: Optional[str] = None
) -> Classroom:
    """สร้าง classroom ใหม่"""
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
    """ดึงข้อมูล classroom ด้วย ID"""
    return db.query(Classroom).filter(
        Classroom.id == classroom_id,
        Classroom.deleted_date.is_(None)
    ).first()


def get_classroom_by_code(db: Session, code: str) -> Optional[Classroom]:
    """ดึงข้อมูล classroom ด้วย code"""
    return db.query(Classroom).filter(
        Classroom.code == code,
        Classroom.deleted_date.is_(None)
    ).first()


def get_classrooms_by_teacher(db: Session, teacher_id: int) -> List[Classroom]:
    """ดึง classroom ทั้งหมดของครู"""
    return db.query(Classroom).filter(
        Classroom.teacher_id == teacher_id,
        Classroom.deleted_date.is_(None)
    ).all()


def get_student_count(db: Session, classroom_id: int) -> int:
    """นับจำนวนนักเรียนใน classroom"""
    return db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).count()


def get_classroom_members(db: Session, classroom_id: int) -> List[dict]:
    """ดึงข้อมูลนักเรียนทั้งหมดใน classroom"""
    members = db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).all()
    
    result = []
    for member in members:
        student = member.student
        if student and student.deleted_date is None:
            user = student.user
            if user and user.deleted_date is None:
                result.append({
                    "student_id": student.student_id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "academy": user.academy,
                    "joined_date": member.created_date
                })
    
    return result


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """ดึงข้อมูล user ด้วย ID"""
    return db.query(User).filter(
        User.id == user_id,
        User.deleted_date.is_(None)
    ).first()


def get_teacher_by_user_id(db: Session, user_id: int) -> Optional[Teacher]:
    """ดึงข้อมูล teacher จาก user_id"""
    return db.query(Teacher).filter(
        Teacher.user_id == user_id,
        Teacher.deleted_date.is_(None)
    ).first()


def get_student_by_user_id(db: Session, user_id: int) -> Optional[Student]:
    """ดึงข้อมูล student จาก user_id"""
    return db.query(Student).filter(
        Student.user_id == user_id,
        Student.deleted_date.is_(None)
    ).first()


def is_student_in_classroom(db: Session, classroom_id: int, student_id: int) -> bool:
    """เช็คว่านักเรียนอยู่ใน classroom แล้วหรือยัง"""
    member = db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
        ClassroomMember.deleted_date.is_(None)
    ).first()
    return member is not None


def add_student_to_classroom(db: Session, classroom_id: int, student_id: int) -> ClassroomMember:
    """เพิ่มนักเรียนเข้า classroom"""
    member = ClassroomMember(
        classroom_id=classroom_id,
        student_id=student_id
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member