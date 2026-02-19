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


# Request — รับจาก form
class CreateAssignmentRequest(BaseModel):
    name: Optional[str] = None
    detail: Optional[str] = None
    startDate: Optional[datetime] = None
    dueDate: Optional[datetime] = None
    isGroup: bool = False
    isPublic: bool = False
    projecttypeId: Optional[int] = None
    languageId: Optional[int] = None
    classroomId: Optional[int] = None


class UpdateAssignmentRequest(BaseModel):
    name: Optional[str] = None
    detail: Optional[str] = None
    startDate: Optional[datetime] = None
    dueDate: Optional[datetime] = None
    isGroup: Optional[bool] = None
    isPublic: Optional[bool] = None
    projecttypeId: Optional[int] = None
    languageId: Optional[int] = None


# Response — ใช้ตัวเดียวกันทุก endpoint
class AssignmentResponse(BaseModel):
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


class DeleteAssignmentResponse(BaseModel):
    message: str