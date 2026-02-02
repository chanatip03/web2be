from sqlalchemy.orm import Session
from app.models.schema import User, Teacher, Role, RoleEnum


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


def get_role_by_name(db: Session, name: RoleEnum):
    return db.query(Role).filter(Role.name == name).first()


def add_role_to_user(db: Session, user: User, role: Role):
    user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
