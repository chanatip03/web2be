from typing import Optional, List
from pydantic import BaseModel
from app.core.user.dto import StudentResponse


class CreateGroupRequest(BaseModel):
    name: str
    assignment_id: int
    member_ids: List[int] = []

    class Config:
        from_attributes = True


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    new_member_ids: Optional[List[int]] = []     
    remove_member_ids: Optional[List[int]] = []

    class Config:
        from_attributes = True


class GroupMemberResponse(BaseModel):
    id: int
    group_id: int
    student: Optional["StudentResponse"] = None

    class Config:
        from_attributes = True


class GroupResponse(BaseModel):
    id: int
    name: str
    assignment_id: int
    members: Optional[List[GroupMemberResponse]] = []

    class Config:
        from_attributes = True


from app.core.user.dto import StudentResponse
GroupMemberResponse.model_rebuild()
GroupResponse.model_rebuild()