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

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

class register_request(BaseModel):
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
    ):
        return cls(
        role=role,
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password,
        academy=academy,
    )
    class Config:
        from_attributes = True

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
    image_url: Optional[str]
    academy: Optional[str]


class StudentInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: Optional[str]
    discord_user_id: Optional[str]


class TeacherInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    certificate_url: Optional[str]
    is_approved: bool


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserBaseResponse
    roles: List[RoleResponse]

    student: Optional[StudentInfo] = None
    teacher: Optional[TeacherInfo] = None