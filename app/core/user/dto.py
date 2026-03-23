from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr
from fastapi import UploadFile

class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    image_url: Optional[str] = None
    academy: str
    class Config:
        from_attributes = True

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
    student_id: str
    discord_user_id: Optional[str] = None
    user: UserResponse

class CreateStudentResponse(BaseModel):
    id: int
    email: EmailStr
    
    class Config:
        from_attributes = True
        
from fastapi import UploadFile


class CreateTeacherRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    certificate: UploadFile

class TeacherResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    certificate_url: str
    is_approved: bool
    user: UserResponse
    
class CreateTeacherResponse(BaseModel):
    id: int
    email: EmailStr
    
    class Config:
        from_attributes = True

