from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password
from . import repository
from app.models.schema import RoleEnum


def create_teacher(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str, certificate_url: str ):
    hashed = hash_password(password)
    user = repository.create_user(db, first_name, last_name, email, hashed, academy)

    role = repository.get_role_by_name(db, RoleEnum.teacher)
    if not role:
        from app.models.schema import Role
        role = Role(name=RoleEnum.teacher)
        db.add(role)
        db.commit()
        db.refresh(role)

    repository.add_role_to_user(db, user, role)
    teacher = repository.create_teacher_profile(db, user, certificate_url)
    return user
