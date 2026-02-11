from typing import Optional
from sqlalchemy.orm import Session
from app.models.schema import User, Student


def create_user(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str | None = None):
    user = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password,
        academy=academy,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_student_profile(db: Session, user: User, student_id: str | None = None, discord_user_id: str | None = None):
    student = Student(
        user_id=user.id,
        student_id=student_id,
        discord_user_id=discord_user_id,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student

def get_student_by_user_id(db: Session, user_id: int) -> Optional[Student]:
    """ดึงข้อมูล student จาก user_id"""
    return db.query(Student).filter(
        Student.user_id == user_id,
        Student.deleted_date.is_(None)
    ).first()
