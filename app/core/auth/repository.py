from sqlalchemy.orm import Session, joinedload
from app.models.schema import Admin , User

def get_admin_by_email(db: Session, email: str):
    return db.query(Admin).filter(Admin.email == email).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_data(db: Session, user_id: int):
    user = (
        db.query(User)
        .options(
            joinedload(User.role),
            joinedload(User.student),
            joinedload(User.teacher),
        )
        .filter(User.id == user_id)
        .first()
    )
    return user


