from pydantic import BaseModel, EmailStr


class CreateStudentRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    academy: str
    student_id: str


class CreateStudentResponse(BaseModel):
    id: int
    email: EmailStr
