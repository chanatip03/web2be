from pydantic import BaseModel, EmailStr
from fastapi import UploadFile


class CreateTeacherRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    certificate: UploadFile


class CreateTeacherResponse(BaseModel):
    id: int
    email: EmailStr
