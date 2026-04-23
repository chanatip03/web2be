from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from app.models.schema import SubmissionTypeEnum
from app.core.user.dto import StudentResponse
    
class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: Optional[int] = None
    student_id: Optional[int] = None
    group_id: Optional[int] = None
    group_name: Optional[str] = None
    submission_type: SubmissionTypeEnum
    project_source_url: Optional[str] = None
    env: str
    testcase_result: Optional[str] = None
    cybersecurity_result: Optional[str] = None
    score: Optional[int] = None
    feedback: Optional[str] = None
    is_late: bool = False
    created_date: Optional[datetime] = None

    students: List[StudentResponse] = []

class ProjectUpdateGradingRequest(BaseModel):
    score: Optional[int] = None
    feedback: Optional[str] = None

class ProjectSourceCodeResponse(BaseModel):
    projectTree: Dict[str, Any]
    files: Dict[str, Any]
