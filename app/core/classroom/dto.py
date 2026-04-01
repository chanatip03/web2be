from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.core.user.dto import TeacherResponse


class CreateClassroomRequest(BaseModel):
    name: str
    semester: str
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None


class ClassroomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    code: str
    semester: str
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None
    teacher: Optional[TeacherResponse] = None


class ClassroomUpdateDTO(BaseModel):
    name: Optional[str] = None
    semester: Optional[str] = None
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None