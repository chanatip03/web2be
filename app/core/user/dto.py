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


class UpdateStudentRequest:
    def __init__(
        self,
        first_name: Optional[str] = Form(None),
        last_name: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        academy: Optional[str] = Form(None),
        student_id: Optional[str] = Form(None),
        image_url: Optional[UploadFile] = File(None),
    ):
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.password = password
        self.academy = academy
        self.student_id = student_id
        self.image_url = image_url

    def dict(self, exclude_unset: bool = False):
        data = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "password": self.password,
            "academy": self.academy,
            "student_id": self.student_id,
            "image_url": self.image_url,
        }
        if exclude_unset:
            return {k: v for k, v in data.items() if v is not None}
        return data


class UpdateTeacherRequest:
    def __init__(
        self,
        first_name: Optional[str] = Form(None),
        last_name: Optional[str] = Form(None),
        email: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        academy: Optional[str] = Form(None),
        image_url: Optional[UploadFile] = File(None),
    ):
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.password = password
        self.academy = academy
        self.image_url = image_url

    def dict(self, exclude_unset: bool = False):
        data = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "password": self.password,
            "academy": self.academy,
            "image_url": self.image_url,
        }
        if exclude_unset:
            return {k: v for k, v in data.items() if v is not None}
        return data


