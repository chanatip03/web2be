from typing import Optional

from pydantic import BaseModel, EmailStr

class CreateAdminRequest(BaseModel):
    email: EmailStr
    password: str


class AdminStudentRow(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    academy: Optional[str] = None
    imageUrl: Optional[str] = None
    studentId: Optional[str] = None


class AdminTeacherRow(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    academy: Optional[str] = None
    imageUrl: Optional[str] = None
    certificateUrl: Optional[str] = None
    isApproved: bool


class AdminTeacherRequestRow(BaseModel):
    id: int
    name: str
    email: str
    academy: Optional[str] = None
    certificateUrl: Optional[str] = None
    imageUrl: Optional[str] = None


class AdminContainerRow(BaseModel):
    id: str
    assignmentName: str
    projectName: str
    studentId: Optional[str] = None
    teacherName: str
    memoryUsageMB: Optional[float] = None
    status: str
    canStop: bool = False