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


def get_role_by_name(db: Session, name: RoleEnum):
    return db.query(Role).filter(Role.name == name).first()


def add_role_to_user(db: Session, user: User, role: Role):
    user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
