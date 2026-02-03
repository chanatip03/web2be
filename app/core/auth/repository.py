from sqlalchemy.orm import Session
from app.models.schema import Admin , User

def get_admin_by_email(db: Session, email: str):
    return db.query(Admin).filter(Admin.email == email).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()



