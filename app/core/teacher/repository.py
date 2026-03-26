from typing import Optional
from sqlalchemy.orm import Session
from app.models.schema import User, Teacher

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