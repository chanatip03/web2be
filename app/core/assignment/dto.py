from fastapi import Form
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from typing import Optional, List
from zoneinfo import ZoneInfo

THAI_TZ = ZoneInfo("Asia/Bangkok")

class ProjectType(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class Language(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class Attachment(BaseModel):
    id: int
    fileUrl: str = Field(..., alias="file_url")

    class Config:
        from_attributes = True
        populate_by_name = True

class CreateAssignmentRequest(BaseModel):
    title:str
    description: Optional[str]
    start_date: datetime
    due_date: datetime
    is_group: bool
    project_type_id: int
    language_id: Optional[int]
    classroom_id: int

    @classmethod
    def as_form(
        cls,
        title: str = Form(..., example="Lab 1: Python Basic"),
        description: str = Form(None, example="Do something"),
        start_date: datetime = Form(...), 
        due_date: datetime = Form(...), 
        is_group: bool = Form(..., example=True),
        project_type_id: int = Form(..., example=1),
        language_id: Optional[int] = Form(None, example=1),
        classroom_id: int = Form(..., example=1),
    ):
        return cls(
            title=title,
            description=description,
            start_date=start_date,
            due_date=due_date,
            is_group=is_group,
            project_type_id=project_type_id,
            language_id=language_id,
            classroom_id=classroom_id,
        )
    
    @field_validator("start_date", "due_date", mode="before")
    @classmethod
    def set_timezone(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=THAI_TZ)
        return v
    
    class Config:
        from_attributes = True
        
class UpdateAssignmentRequest(BaseModel):
    title: Optional[str]
    description: Optional[str]
    start_date: Optional[datetime]
    due_date: Optional[datetime]
    is_group: Optional[bool]
    is_public: Optional[bool]
    project_type_id: Optional[int]
    language_id: Optional[int]
    delete_attachment_ids: Optional[List[int]]
    delete_testcase_url: Optional[str]
    classroom_id: int

    @field_validator("delete_attachment_ids", mode="before")
    @classmethod
    def parse_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @classmethod
    def as_form(
        cls,
        title: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        start_date: Optional[datetime] = Form(None),
        due_date: Optional[datetime] = Form(None),
        is_group: Optional[bool] = Form(None),
        is_public: Optional[bool] = Form(None),
        project_type_id: Optional[int] = Form(None),
        language_id: Optional[int] = Form(None),
        classroom_id: int = Form(...),
        delete_attachment_ids: Optional[str] = Form(None), 
        delete_testcase_url: Optional[str] = Form(None),
    ):
        return cls(
            title=title,
            description=description,
            start_date=start_date,
            due_date=due_date,
            is_group=is_group,
            is_public=is_public,
            project_type_id=project_type_id,
            language_id=language_id,
            classroom_id=classroom_id,
            delete_attachment_ids=delete_attachment_ids, 
            delete_testcase_url=delete_testcase_url,
        )
        
    @field_validator("start_date", "due_date", mode="before")
    @classmethod
    def set_timezone(cls, v):
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=THAI_TZ)
        return v

    class Config:
        from_attributes = True

class AssignmentResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    start_date: datetime
    due_date: datetime
    is_group: bool
    is_public: bool

    projectType: ProjectType = Field(..., alias="project_type")
    language: Optional[Language]
    testcaseUrl: Optional[str] = Field(None, alias="testcase_url")
    attachments: List[Attachment]

    class Config:
        from_attributes = True
        populate_by_name = True


class DeleteAssignmentResponse(BaseModel):
    message: str