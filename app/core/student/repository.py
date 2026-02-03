from sqlalchemy.orm import Session
from app.models.schema import User, Student, Role, role_users, RoleEnum


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
