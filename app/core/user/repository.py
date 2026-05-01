from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import func
from app.models.schema import Student, Teacher, User, Role

def create_user(db: Session, user: User):
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

def get_users_by_role(db: Session, role_name: Optional[str] = None):
    query = db.query(User).join(Role).filter(User.deleted_date.is_(None))
    if role_name:
        query = query.filter(Role.name == role_name)
    return query.all()

def get_user_with_student(db: Session, user_id: int):
    return db.query(User).options(joinedload(User.student)).filter(
        User.id == user_id, 
        User.deleted_date.is_(None)
    ).first()

def get_user_with_teacher(db: Session, user_id: int):
    return db.query(User).options(joinedload(User.teacher)).filter(
        User.id == user_id, 
        User.deleted_date.is_(None)
    ).first()

def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(
        User.id == user_id, 
        User.deleted_date.is_(None)
    ).first()

def soft_delete_user(db: Session, user: User):
    user.deleted_date = func.now()
    db.commit()
    db.refresh(user)
    return user

def update_student_data(db: Session, user: User, student: Student, user_data: dict, student_id: Optional[str] = None):
    for key, value in user_data.items():
        if value is not None:
            setattr(user, key, value)
    if student_id is not None:
        student.student_id = student_id
    db.commit()
    db.refresh(user)
    db.refresh(student)
    return user

def update_teacher_data(db: Session, user: User, teacher: Teacher, user_data: dict):
    for key, value in user_data.items():
        if value is not None:
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    db.refresh(teacher)
    return user
