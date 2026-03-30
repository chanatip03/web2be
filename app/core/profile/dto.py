from pydantic import BaseModel
from typing import Optional


class ProfileResponse(BaseModel):
    """ข้อมูล profile ของ user"""
    id: int
    first_name: str
    last_name: str
    email: str
    academy: Optional[str] = None
    image_url: Optional[str] = None
    # student-specific
    student_id: Optional[str] = None
    discord_user_id: Optional[str] = None
    # teacher-specific
    certificate_url: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    """แก้ไขข้อมูล profile"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    academy: Optional[str] = None
    # student-specific
    student_id: Optional[str] = None


class UpdateProfileResponse(BaseModel):
    """response หลังแก้ไข profile"""
    message: str
    first_name: str
    last_name: str
    email: str
    academy: Optional[str] = None
    image_url: Optional[str] = None
    student_id: Optional[str] = None


class UploadImageResponse(BaseModel):
    """response หลังอัปโหลดรูปโปรไฟล์"""
    message: str
    image_url: str
