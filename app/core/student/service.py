from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password
from app.models.schema import RoleEnum
from app.utils.role import get_role_by_name, add_role_to_user
from app.core.student.repository import create_user, create_student_profile

def create_student(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str | None = None, student_id: str | None = None):
    # hash password
    hashed = hash_password(password)
    user = create_user(db, first_name, last_name, email, hashed, academy)

    # ensure role exists
    role = get_role_by_name(db, RoleEnum.student)
    if not role:
        # create role lazily
        from app.models.schema import Role
        role = Role(name=RoleEnum.student)
        db.add(role)
        db.commit()
        db.refresh(role)

    add_role_to_user(db, user, role)
    create_student_profile(db, user, student_id)
    return user
