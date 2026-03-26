from pydantic import BaseModel
from typing import Optional
from typing import Optional

from app.core.teacher.dto import TeacherResponse

class CreateClassroomRequest(BaseModel):
    name: str
    semester: str
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None

class ClassroomResponse(BaseModel):
    id: int
    name: str
    code: str
    semester: str
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None
    teacher: TeacherResponse
    class Config:
        from_attributes = True

class ClassroomUpdateDTO(BaseModel):
    name: Optional[str]
    semester: Optional[str]
    description: Optional[str]
    learningoutcomes: Optional[str] = None

