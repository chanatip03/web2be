from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from typing import Optional
from datetime import datetime

from app.core.student.dto import StudentResponse
from app.core.teacher.dto import TeacherResponse

class CreateClassroomRequest(BaseModel):
    name: str
    semester: str
    description: Optional[str] = None
    learning_out_come: Optional[str] = None

class ClassroomResponse(BaseModel):
    id: int
    name: str
    code: str
    semester: str
    description: Optional[str] = None
    learning_out_come: Optional[str] = None
    excel_link: str
    teacher: TeacherResponse
    class Config:
        from_attributes = True

class ClassroomMemberResponse(BaseModel):
    id: int
    student: StudentResponse
    classroom_id: int
    joined_date: datetime
    class Config:
        from_attributes = True

class ClassroomUpdateDTO(BaseModel):
    name: Optional[str]
    semester: Optional[str]
    description: Optional[str]
    learning_outcomes: Optional[str] = None

