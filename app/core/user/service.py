from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password
from app.models.schema import User
from .repository import get_role_by_name, add_role_to_user, create_user, create_student_profile, create_teacher_profile


def create_user_service(db: Session, role: str, first_name: str, last_name: str, email: str, password: str, academy: str, certificate_url: str | None = None, student_id: str | None = None):
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
    
    role_db = get_role_by_name(db, role)

    add_role_to_user(db, user, role_db)
    if(role == "teacher"):
        create_teacher_profile(db, user, certificate_url)
    elif(role == "student"):
        create_student_profile(db,user,student_id)
    return user