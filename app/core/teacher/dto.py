from xmlrpc.client import boolean
from pydantic import BaseModel, ConfigDict, EmailStr
from fastapi import UploadFile


class CreateTeacherRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    certificate: UploadFile
class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    image_url: str | None
    academy: str
    class Config:
        from_attributes = True

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
