
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.schema import ClassroomMember

def add_student_to_classroom(db: Session, member: ClassroomMember) -> ClassroomMember:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member

def is_student_in_classroom(db: Session, classroom_id: int, student_id: int) -> bool:
    """เช็คว่านักเรียนอยู่ใน classroom แล้วหรือยัง"""
    return ( db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
        ClassroomMember.deleted_date.is_(None)
    ).first()
    )

def get_classroon_member(db: Session, classroom_id: int) -> list[ClassroomMember]:
    return(db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).all()
    )

def delete_classroom_member(db: Session, classroom_id: int, student_id: int) -> ClassroomMember:
    member = db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
        ClassroomMember.deleted_date.is_(None)
    ).first()
    if member:
        member.deleted_date = datetime.now(timezone.utc)
        db.commit()
        db.refresh(member)
    return member