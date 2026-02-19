from sqlalchemy.orm import Session
from app.utils.user import create_user
from app.utils.generate_token import hash_password
from app.models.schema import RoleEnum, User
from app.utils.role import get_role_by_name, add_role_to_user
from .repository import create_teacher_profile

def create_teacher(db: Session, first_name: str, last_name: str, email: str, password: str, academy: str, certificate_url: str ):
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
    
    role = get_role_by_name(db, RoleEnum.teacher)
    if not role:
        from app.models.schema import Role
        role = Role(name=RoleEnum.teacher)
        db.add(role)
        db.commit()
        db.refresh(role)

    add_role_to_user(db, user, role)
    create_teacher_profile(db, user, certificate_url)
    return user