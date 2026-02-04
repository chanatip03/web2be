from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreateClassroomRequest(BaseModel):
    name: str
    semester: str
    description: Optional[str] = None


class CreateClassroomResponse(BaseModel):
    id: int
    name: str
    code: str
    semester: str
    teacher_id: int
    
    class Config:
        from_attributes = True


class ClassroomResponse(BaseModel):
    id: int
    name: str
    code: str
    semester: str
    description: Optional[str] = None
    teacher_id: int
    teacher_name: str
    student_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class ClassroomListResponse(BaseModel):
    classrooms: list[ClassroomResponse]
    total: int