from pydantic import BaseModel
from typing import Optional
from typing import Optional

from app.core.user.dto import TeacherResponse

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
    teacher: Optional["TeacherResponse"] = None
    class Config:
        from_attributes = True

class ClassroomUpdateDTO(BaseModel):
    name: Optional[str] = None
    semester: Optional[str] = None
    description: Optional[str] = None
    learningoutcomes: Optional[str] = None
    

from app.core.user.dto import TeacherResponse


ClassroomResponse.model_rebuild()