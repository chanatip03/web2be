from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.core.user.dto import StudentResponse


class JoinClassroomRequest(BaseModel):
    code: str

    model_config = ConfigDict(from_attributes=True)


class ClassroomMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student: Optional[StudentResponse] = None
    classroom_id: int