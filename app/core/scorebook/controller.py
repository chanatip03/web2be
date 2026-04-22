from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from .service import get_scorebook_data

router = APIRouter(prefix="/scorebook", tags=["Scorebook"])

@router.get("/teacher/{classroom_id}")
def teacher_scorebook(classroom_id: int, db: Session = Depends(get_db)):
    return get_scorebook_data(db, classroom_id)
