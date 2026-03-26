from datetime import datetime
from typing import Optional
from fastapi import Form, UploadFile
from pydantic import BaseModel, EmailStr , field_validator

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    
class VerifyOtpRequest(BaseModel):
    email: str
    otp: str
    
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