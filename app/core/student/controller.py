from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import CreateStudentRequest, CreateStudentResponse
from .service import create_student
from app.models.schema import User

router = APIRouter(prefix="/student", tags=["Student"])


@router.post("/", response_model=CreateStudentResponse)
def register_student(data: CreateStudentRequest, db: Session = Depends(get_db)):
    # check if user exists
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        user = create_student(db, data.first_name, data.last_name, data.email, data.password, data.academy, data.student_id)
        return CreateStudentResponse(id=user.id, email=user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
