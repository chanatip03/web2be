from sqlalchemy.orm import Session

from app.utils.generate_token import verify_password
from app.models.schema import Admin
from . import repository

def authenticate_user(db: Session, email: str, password: str):
    user = repository.get_user_by_email(db, email)
    if not user:
        return None

    if not verify_password(password, user.password):
        return None

    return user


def authenticate_admin(db: Session, email: str, password: str):
    admin = repository.get_admin_by_email(db, email)
    if not admin:
        return None

    if not verify_password(password, admin.password):
        return None

    return admin

def get_user_data_service(db: Session, current_user: dict):
    if current_user.get("role") == "admin":
        return db.query(Admin).filter(Admin.id == current_user["id"]).first()

    user = repository.get_user_data(db, current_user["id"])

    return user
