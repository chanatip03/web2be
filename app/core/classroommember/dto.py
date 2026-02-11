from pydantic import BaseModel

from app.core.student.dto import StudentResponse

class ClassroomMemberResponse(BaseModel):
    id: int
    student: StudentResponse
    classroom_id: int
    class Config:
        from_attributes = True