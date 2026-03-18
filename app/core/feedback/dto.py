from pydantic import BaseModel
from typing import Optional


class FeedbackResponse(BaseModel):
    project_id: int
    score: Optional[int] = None
    feedback: Optional[str] = None

    class Config:
        from_attributes = True