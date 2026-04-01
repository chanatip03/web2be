from typing import List, Optional
from fastapi import Form
from pydantic import BaseModel, ConfigDict, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class VerifyOtpRequest(BaseModel):
    email: str
    otp: str


class RegisterRequest(BaseModel):
    """Registration request DTO. Use RegisterRequest.as_form() for multipart/form-data endpoints."""
    role: str
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    student_id: Optional[str] = None
    certificate_url: Optional[str] = None

    @classmethod
    def as_form(
        cls,
        role: str = Form(...),
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: EmailStr = Form(...),
        password: str = Form(...),
        academy: str = Form(...),
        student_id: Optional[str] = Form(None),
    ):
        return cls(
            role=role,
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
            academy=academy,
            student_id=student_id,
        )

    model_config = ConfigDict(from_attributes=True)


# Keep backward-compat alias
register_request = RegisterRequest


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    email: EmailStr
    image_url: Optional[str] = None
    academy: Optional[str] = None


class StudentInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: Optional[str] = None
    discord_user_id: Optional[str] = None


class TeacherInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    certificate_url: Optional[str] = None
    is_approved: bool


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserBaseResponse
    roles: List[RoleResponse]

    student: Optional[StudentInfo] = None
    teacher: Optional[TeacherInfo] = None