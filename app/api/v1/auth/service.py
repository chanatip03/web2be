from sqlalchemy.orm import Session

from app.core.security import verify_password
from . import repository


def authenticate_admin(db: Session, email: str, password: str):
    admin = repository.get_admin_by_email(db, email)
    if not admin:
        return None

    if not verify_password(password, admin.password):
        return None

    return admin
