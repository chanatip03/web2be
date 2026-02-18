from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class ProjectTypeResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class LanguageResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class AttachmentResponse(BaseModel):
    id: int
    fileUrl: str

    class Config:
        from_attributes = True


class CreateAssignmentResponse(BaseModel):
    id: int
    name: str
    detail: Optional[str] = None
    startDate: datetime
    dueDate: datetime
    isGroup: bool
    isPublic: bool
    projectType: ProjectTypeResponse
    language: LanguageResponse
    testcaseUrl: Optional[str] = None
    attachments: List[AttachmentResponse]

    class Config:
        from_attributes = True