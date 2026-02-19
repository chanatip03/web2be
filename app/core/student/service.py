from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password
from app.models.schema import RoleEnum, User
from app.utils.role import get_role_by_name, add_role_to_user
from app.core.student.repository import create_student_profile
from app.utils.user import create_user

def create_student(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str | None = None, student_id: str | None = None):
    hashed = hash_password(password)
    user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=hashed,
            academy=academy
        )
    
    if not create_user(db, user):
        raise TypeError("Create user failed")

    role = get_role_by_name(db, RoleEnum.student)
    if not role:
        from app.models.schema import Role
        role = Role(name=RoleEnum.student)
        db.add(role)
        db.commit()
        db.refresh(role)

    add_role_to_user(db, user, role)
    create_student_profile(db, user, student_id)
    return user