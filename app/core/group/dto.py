from typing import Optional, List
from pydantic import BaseModel, ConfigDict

from app.core.user.dto import StudentResponse


class CreateGroupRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    assignment_id: int
    member_ids: List[int] = []


class UpdateGroupRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str] = None
    new_member_ids: Optional[List[int]] = []
    remove_member_ids: Optional[List[int]] = []


class GroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    student: Optional[StudentResponse] = None


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    assignment_id: int
    members: Optional[List[GroupMemberResponse]] = []