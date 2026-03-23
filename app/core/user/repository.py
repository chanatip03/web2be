from typing import Optional

from sqlalchemy.orm import Session
from app.models.schema import Student, Teacher, User, Role

def create_user(db: Session, user: User):
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_role_by_name(db: Session, name: str):
    return db.query(Role).filter(Role.name == name).first()


def add_role_to_user(db: Session, user: User, role: Role):
    user.roles.append(role)
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
    return db.query(Teacher).filter(
        Teacher.user_id == user_id,
        Teacher.deleted_date.is_(None)
    ).first()
    
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

def get_student_by_user_id(db: Session, user_id: int) -> bool:
    return db.query(Student).filter(
        Student.user_id == user_id,
        Student.deleted_date.is_(None)
    ).first()