from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.utils.validator import get_current_user
from .dto import ProfileResponse, UpdateProfileRequest, UpdateProfileResponse, UploadImageResponse
from . import service

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=ProfileResponse)
def get_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return service.get_profile_service(db=db, user_id=current_user["id"])


@router.patch("", response_model=UpdateProfileResponse)
def update_profile(
    request: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return service.update_profile_service(db=db, user_id=current_user["id"], request=request)


@router.post("/image", response_model=UploadImageResponse)
def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return service.upload_profile_image_service(db=db, user_id=current_user["id"], file=file)