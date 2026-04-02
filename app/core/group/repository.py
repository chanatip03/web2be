from sqlalchemy.orm import Session, joinedload
from sqlalchemy import exists
from app.models.schema import Student, GroupMember, Group, ClassroomMember

def create_group(db: Session, name: str, assignment_id: int) -> Group:
    group = Group(
        name=name,
        assignment_id=assignment_id
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group

def create_group_member(db: Session, group_id: int, student_id: int) -> GroupMember:
    member = GroupMember(
        group_id=group_id,
        student_id=student_id
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member

def get_group_members(db: Session, group_id: int):
    return  (
        db.query(Group)
        .options(
            joinedload(Group.members).joinedload(GroupMember.student)
        )
        .filter(Group.id == group_id)
        .first()
    )
    
def get_available_member(db: Session, assignment_id: int, classroom_id: int):
    return (
        db.query(Student)
        .join(ClassroomMember, ClassroomMember.student_id == Student.id)
        .filter(
            ClassroomMember.classroom_id == classroom_id,
            ~db.query(GroupMember)
            .join(Group)
            .filter(
                Group.assignment_id == assignment_id,
                GroupMember.student_id == Student.id
            )
            .exists()
        )
        .all()
    )

def get_user_group_by_assignment(db: Session, student_id: int, assignment_id: int):
    return (
        db.query(Group)
        .join(GroupMember)
        .options(
            joinedload(Group.members).joinedload(GroupMember.student)
        )
        .filter(
            Group.assignment_id == assignment_id,
            GroupMember.student_id == student_id
        )
        .first()
    )