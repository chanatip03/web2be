from sqlalchemy.orm import Session
from fastapi import HTTPException
from . import repository


def create_admin(db: Session, email: str, password: str):
    if repository.get_admin_by_email(db, email):
        raise HTTPException(
            status_code=400,
            detail="Admin email already exists",
        )

    return repository.create_admin(db, email, password)
