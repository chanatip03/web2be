from pydantic import BaseModel, EmailStr
from typing import Optional


class FeedbackResponse(BaseModel):
    project_id: int
    score: Optional[int] = None
    feedback: Optional[str] = None

    class Config:
        from_attributes = True


class FeedbackNotifyRequest(BaseModel):
    email: EmailStr
    discord_user_id: str
    feedback_text: str


class FeedbackNotifyResponse(BaseModel):
    email_sent: bool
    discord_sent: bool
    email_error: Optional[str] = None
    discord_error: Optional[str] = None