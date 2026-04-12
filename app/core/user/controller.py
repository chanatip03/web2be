from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from .dto import UpdateUserRequest
from .service import update_user_service

router = APIRouter()

@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: int, request: UpdateUserRequest, db: Session = Depends(get_db)):
    user_data = request.dict(exclude_unset=True)
    student_id = user_data.pop("student_id", None)

    try:
        updated_user = update_user_service(db, user_id, user_data, student_id)
        return updated_user
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))