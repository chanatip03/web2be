from pydantic import BaseModel, EmailStr

class CreateAdminRequest(BaseModel):
    email: EmailStr
    password: str