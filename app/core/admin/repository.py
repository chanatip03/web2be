from sqlalchemy.orm import Session
from app.models.schema import Admin
from app.utils.generate_token import hash_password

def create_admin(db: Session, email: str, password: str):
    try:
        admin = Admin(
            email=email,
            password=hash_password(password),
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin
    except Exception:
        db.rollback()
        raise

def get_admin_by_email(db: Session, email: str):
    return db.query(Admin).filter(Admin.email == email).first()
