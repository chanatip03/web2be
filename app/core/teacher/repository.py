from typing import Optional
from sqlalchemy.orm import Session
from app.models.schema import User, Teacher
from app.models.schema import User, Teacher

def create_user(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str):
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


def create_teacher_profile(db: Session, user: User, certificate_url: str):
    teacher = Teacher(
        user_id=user.id,
        certificate_url=certificate_url,
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher

def get_teacher_by_user_id(db: Session, user_id: int) -> Optional[Teacher]:
    """ดึงข้อมูล teacher จาก user_id"""
    return db.query(Teacher).filter(
        Teacher.user_id == user_id,
        Teacher.deleted_date.is_(None)
    ).first()