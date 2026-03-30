from sqlalchemy.orm import Session
from typing import Optional

from app.models.schema import User, Student, Teacher

def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """ดึงข้อมูล user ด้วย id"""
    return db.query(User).filter(
        User.id == user_id,
        User.deleted_date.is_(None)
    ).first()


def get_student_by_user_id(db: Session, user_id: int) -> Optional[Student]:
    """ดึงข้อมูล student ด้วย user_id"""
    return db.query(Student).filter(
        Student.user_id == user_id,
        Student.deleted_date.is_(None)
    ).first()


def get_teacher_by_user_id(db: Session, user_id: int) -> Optional[Teacher]:
    """ดึงข้อมูล teacher ด้วย user_id"""
    return db.query(Teacher).filter(
        Teacher.user_id == user_id,
        Teacher.deleted_date.is_(None)
    ).first()


def update_user(
    db: Session,
    user: User,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    academy: Optional[str] = None,
    image_url: Optional[str] = None,
) -> User:
    """แก้ไขข้อมูล user"""
    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name
    if academy is not None:
        user.academy = academy
    if image_url is not None:
        user.image_url = image_url
    db.commit()
    db.refresh(user)
    return user


def update_student(
    db: Session,
    student: Student,
    student_id: Optional[str] = None,
) -> Student:
    """แก้ไขข้อมูล student (เช่น รหัสนักศึกษา)"""
    if student_id is not None:
        student.student_id = student_id
    db.commit()
    db.refresh(student)
    return student
