from fastapi import UploadFile
from fastapi import File
from typing import Optional
from fastapi import Form
from pydantic import BaseModel, ConfigDict, EmailStr

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    email: EmailStr
    image_url: Optional[str] = None
    academy: Optional[str] = None


class CreateStudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    student_id: str


class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: Optional[str] = None
    discord_user_id: Optional[str] = None
    user: UserResponse


class CreateStudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr


class CreateTeacherRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str


class TeacherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    certificate_url: Optional[str] = None
    is_approved: bool
    user: UserResponse


class CreateTeacherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr


class UpdateStudentRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    academy: Optional[str] = None
    student_id: Optional[str] = None
    image_url: Optional[UploadFile] = File(None)

class UpdateTeacherRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    academy: Optional[str] = None
    image_url: Optional[UploadFile] = File(None)
    is_verify: Optional[bool] = False


