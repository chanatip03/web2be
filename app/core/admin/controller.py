from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import CreateAdminRequest
from .service import create_admin

router = APIRouter(prefix="/admin")

@router.post("/")
def create_admin_user(
    data: CreateAdminRequest,
    db: Session = Depends(get_db),
):
    admin = create_admin(db, data.email, data.password)
    return {"id": admin.id, "email": admin.email}
