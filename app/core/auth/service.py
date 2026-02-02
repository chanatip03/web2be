from sqlalchemy.orm import Session

from app.utils.generate_token import verify_password
from . import repository
from app.models.schema import User


def authenticate_user(db: Session, email: str, password: str):
    user = db.query(User).filter(User.email == email).first()
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
