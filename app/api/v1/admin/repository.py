from sqlalchemy.orm import Session
from app.models.schema import Admin
from app.core.security import hash_password

def create_admin(db: Session, email: str, password: str):
    admin = Admin(
        email=email,
        password=hash_password(password),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin
