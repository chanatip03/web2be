from typing import Optional, Union, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.utils.validator import get_current_user
from .dto import (
    UpdateStudentRequest, UpdateTeacherRequest, UserResponse, 
    StudentResponse, TeacherResponse
)
from .service import (
    update_student_service, update_teacher_service, get_users_service,
    get_current_user_info_service, soft_delete_user_service
)

router = APIRouter(prefix="/user", tags=["User"])

@router.get("/", response_model=List[UserResponse])
def get_users_endpoint(role: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        users = get_users_service(db, role)
        return users
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/me", response_model=Union[StudentResponse, TeacherResponse, UserResponse])
def get_current_user_endpoint(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    try:
        data = get_current_user_info_service(db, current_user)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

from fastapi import APIRouter, Depends, HTTPException, status, Form, UploadFile, File
import uuid
from app.utils.r2 import upload_file

@router.put("/student/{user_id}", response_model=StudentResponse)
async def update_student_endpoint(
    user_id: int, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user),
    payload: UpdateStudentRequest = Depends(UpdateStudentRequest.as_form),
):
    user_data = payload.dict(exclude_unset=True)
    student_id = user_data.pop("student_id", None)
    image = user_data.pop("image_url", None)
    
    if image is not None and image.filename:
        image_bytes = await image.read()
        extension = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
        key = f"profiles/user_{user_id}_{uuid.uuid4().hex[:8]}.{extension}"
        _, url = upload_file(key, image_bytes, content_type=image.content_type)
        user_data["image_url"] = url

    try:
        student = update_student_service(db, current_user, user_id, user_data, student_id)
        return student
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/teacher/{user_id}", response_model=TeacherResponse)
async def update_teacher_endpoint(
    user_id: int, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user),
    payload: UpdateTeacherRequest = Depends(UpdateTeacherRequest.as_form),
):
    user_data = payload.dict(exclude_unset=True)
    image = user_data.pop("image_url", None)
    
    if image is not None and image.filename:
        image_bytes = await image.read()
        extension = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
        key = f"profiles/user_{user_id}_{uuid.uuid4().hex[:8]}.{extension}"
        _, url = upload_file(key, image_bytes, content_type=image.content_type)
        user_data["image_url"] = url

    try:
        teacher = update_teacher_service(db, current_user, user_id, user_data)
        return teacher
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_endpoint(
    user_id: int, 
    db: Session = Depends(get_db), 
    current_user: dict = Depends(get_current_user)
):
    try:
        soft_delete_user_service(db, current_user, user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))