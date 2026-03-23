from typing import Optional

from pydantic import BaseModel

from app.core.user.dto import StudentResponse

class JoinClassroomRequest(BaseModel):
    code: str
    
    class Config :
        from_attribute = True
    
class ClassroomMemberResponse(BaseModel):
    id: int
    student: Optional["StudentResponse"] =None
    classroom_id: int
    class Config:
        from_attributes = True
        
from app.core.user.dto import StudentResponse

ClassroomMemberResponse.model_rebuild()