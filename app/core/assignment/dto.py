from fastapi import Form
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List

# UTC+7 fixed offset — works on Windows without the tzdata package
THAI_TZ = timezone(timedelta(hours=7))


class ProjectType(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class Language(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class Attachment(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    fileUrl: str = Field(..., alias="file_url")


class CreateAssignmentRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    description: Optional[str] = ""
    start_date: datetime
    due_date: datetime
    is_group: bool
    project_type_id: int
    language_id: Optional[int] = None
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


class UpdateAssignmentRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    is_group: Optional[bool] = None
    is_public: Optional[bool] = None
    project_type_id: Optional[int] = None
    language_id: Optional[int] = None
    delete_attachment_ids: Optional[List[int]] = None
    delete_testcase_url: Optional[str] = None
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


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    title: str
    description: Optional[str] = None
    start_date: datetime
    due_date: datetime
    is_group: bool
    is_public: bool

    projectType: ProjectType = Field(..., alias="project_type")
    language: Optional[Language] = None
    testcaseUrl: Optional[str] = Field(None, alias="testcase_url")
    plagiarism_result: Optional[Any] = None
    attachments: List[Attachment] = []


class DeleteAssignmentResponse(BaseModel):
    message: str
