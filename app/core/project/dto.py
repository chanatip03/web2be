from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from app.models.schema import SubmissionTypeEnum
from app.core.user.dto import StudentResponse
    
class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: Optional[int] = None
    submission_type: SubmissionTypeEnum
    project_source_url: Optional[str] = None
    env: str
    testcase_result: Optional[str] = None
    cybersecurity_result: Optional[str] = None
    score: Optional[int] = None
    feedback: Optional[str] = None
    submission_id: Optional[str] = None
    
    students: List[StudentResponse] = []

class ProjectUpdateGradingRequest(BaseModel):
    score: Optional[int] = None
    feedback: Optional[str] = None
