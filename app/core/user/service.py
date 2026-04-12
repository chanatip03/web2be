from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password
from app.models.schema import User
from .repository import create_user, create_student_profile, create_teacher_profile


def create_user_service(db: Session, role_id: int, first_name: str, last_name: str, email: str, password: str, academy: str, certificate_url: str | None = None, student_id: str | None = None):
    hashed = hash_password(password)
    user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=hashed,
            academy=academy,
            role_id=role_id
        )
    
    if not create_user(db, user):
        raise TypeError("Create user failed")
    
    if(role_id == 1):
        create_student_profile(db,user,student_id)
    elif(role_id == 2):
        create_teacher_profile(db, user, certificate_url)
    return user


def update_user_service(db: Session, user_id: int, user_data: dict, student_id: Optional[str] = None):
    user = update_user_and_student_id(db, user_id, user_data, student_id)
    if not user:
        raise ValueError("User not found or update failed")
    return user