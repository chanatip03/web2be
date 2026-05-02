from typing import Optional
from sqlalchemy.orm import Session
from app.utils.generate_token import hash_password, verify_password
from app.models.schema import User
from .repository import (
    create_user, create_student_profile, create_teacher_profile,
    get_users_by_role, get_user_with_student, get_user_with_teacher,
    get_user_by_id, soft_delete_user, update_student_data, update_teacher_data, update_password_by_email, update_password_by_user_id
)


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

def get_users_service(db: Session, role_name: Optional[str] = None):
    return get_users_by_role(db, role_name)

def get_current_user_info_service(db: Session, current_user: dict):
    user_id = current_user["id"]
    if current_user["role"] == "student":
        user_info = get_user_with_student(db, user_id)
        if not user_info:
            raise ValueError("Student not found")
        return user_info.student 
    elif current_user["role"] == "teacher":
        user_info = get_user_with_teacher(db, user_id)
        if not user_info:
            raise ValueError("Teacher not found")
        return user_info.teacher
    elif current_user["role"] == "admin":
        from app.models.schema import Admin
        admin = db.query(Admin).filter(Admin.id == user_id).first()
        if not admin:
            raise ValueError("Admin not found")
        return admin
    else:
        user_info = get_user_by_id(db, user_id)
        if not user_info:
            raise ValueError("User not found")
        return user_info

def update_student_service(db: Session, current_user: dict, user_id: int, user_data: dict, student_id: Optional[str] = None):
    if current_user["id"] != user_id and current_user.get("role") != "admin":
        raise ValueError("Cannot update other user's profile")
    
    user_info = get_user_with_student(db, user_id)
    if not user_info or not user_info.student:
        raise ValueError("Student not found")

    if 'password' in user_data and user_data['password']:
        user_data['password'] = hash_password(user_data['password'])
        
    updated_user = update_student_data(db, user_info, user_info.student, user_data, student_id)
    return updated_user.student

def update_teacher_service(db: Session, current_user: dict, user_id: int, user_data: dict):
    if current_user["id"] != user_id and current_user.get("role") != "admin":
        raise ValueError("Cannot update other user's profile")

    user_info = get_user_with_teacher(db, user_id)
    if not user_info or not user_info.teacher:
        raise ValueError("Teacher not found")

    if 'password' in user_data and user_data['password']:
        user_data['password'] = hash_password(user_data['password'])
        
    updated_user = update_teacher_data(db, user_info, user_info.teacher, user_data)
    return updated_user.teacher

def soft_delete_user_service(db: Session, current_user: dict, user_id: int):
    if current_user["id"] != user_id and current_user.get("role") != "admin":
        raise ValueError("Unauthorized to delete user")
    user = get_user_by_id(db, user_id)
    if not user:
        raise ValueError("User not found")
    soft_delete_user(db, user)
    return True

def update_user_password_service(
    db: Session,
    email: str,
    new_password: str
):
    hashed = hash_password(new_password)

    user = update_password_by_email(
        db=db,
        email=email,
        password=hashed
    )

    if not user:
        raise ValueError("User not found")

    return True


def change_user_password_service(
    db: Session,
    user_id: int,
    old_password: str,
    new_password: str
):
    user = get_user_by_id(db, user_id)

    if not user:
        raise ValueError(status_code=404, detail="User not found")


    if not verify_password(old_password, user.password):
        raise ValueError("Old password incorrect")

    hashed = hash_password(new_password)

    updated_user = update_password_by_user_id(
        db=db,
        user_id=user_id,
        hashed_password=hashed
    )

    return updated_user