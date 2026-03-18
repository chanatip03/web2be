from pydantic import BaseModel
from typing import Optional


# ---------- Request ----------

class UpsertScorebookRequest(BaseModel):
    score: Optional[int] = None
    feedback: Optional[str] = None


# ---------- Response ----------

class StudentInfo(BaseModel):
    id: int
    first_name: str
    last_name: str
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


class ScorebookResponse(BaseModel):
    project_id: int
    student: StudentInfo
    score: Optional[int] = None
    feedback: Optional[str] = None

    class Config:
        from_attributes = True