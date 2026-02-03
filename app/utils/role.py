from sqlalchemy.orm import Session
from app.models.schema import User, Role, RoleEnum

def get_role_by_name(db: Session, name: RoleEnum):
    return db.query(Role).filter(Role.name == name).first()


def add_role_to_user(db: Session, user: User, role: Role):
    user.roles.append(role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user