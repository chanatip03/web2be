from pydantic import BaseModel, ConfigDict, EmailStr

class CreateStudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    student_id: str

class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    image_url: str | None
    academy: str
    class Config:
        from_attributes = True

class StudentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    student_id: str
    discord_user_id: str | None
    user: UserResponse

class CreateStudentResponse(BaseModel):
    id: int
    email: EmailStr
    
    class Config:
        from_attributes = True
