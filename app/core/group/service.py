from sqlalchemy.orm import Session
from app.core.user.repository import get_student_by_user_id
from app.models.schema import Group, GroupMember
from .repository import (
    create_group,
    create_group_member,
    get_group_members,
    get_available_member,
    get_user_group_by_assignment,
)

def create_group_service(
    db: Session,
    user_id: int,
    name: str,
    assignment_id: int,
    member_ids: list[int]
):
    student = get_student_by_user_id(db, user_id)
    if not student:
        raise ValueError("User is not a student")

    group = create_group(db, name, assignment_id)

    create_group_member(db, group.id, student.id)

    for member_id in member_ids:
        if member_id != student.id:
            create_group_member(db, group.id, member_id)

    return get_group_members(db, group.id)


def get_group_members_service(db: Session, group_id: int):
    group = get_group_members(db, group_id)
    if not group:
        raise ValueError("Group members not found")
    return group


def get_available_member_service(db: Session, assignment_id: int, classroom_id: int):
    students = get_available_member(db, assignment_id, classroom_id)
    return students


def get_user_group_service(db: Session, user_id: int, assignment_id: int):
    student = get_student_by_user_id(db, user_id)
    if not student:
        raise ValueError("User is not a student")
    
    group = get_user_group_by_assignment(db, student.id, assignment_id)
    return group


def update_group_service(
    db: Session,
    group_id: int,
    name: str | None,
    new_member_ids: list[int],
    remove_member_ids: list[int],
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise ValueError("Group not found")

    if name:
        group.name = name

    for member_id in new_member_ids:
        create_group_member(db, group_id, member_id)

    for member_id in remove_member_ids:
        member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.student_id == member_id
        ).first()

        if member:
            db.delete(member)

    db.commit()
    db.refresh(group)
    return get_group_members(db, group.id)