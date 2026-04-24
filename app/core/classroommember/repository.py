
from sqlalchemy.orm import Session, joinedload
from app.models.schema import Classroom, ClassroomMember

def add_student_to_classroom(db: Session, member: ClassroomMember) -> ClassroomMember:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member

def get_classroom_member_by_id(db: Session, member_id: int):
    return db.query(ClassroomMember).options(joinedload(ClassroomMember.student)).filter(ClassroomMember.id == member_id).first()

def is_student_in_classroom(db: Session, classroom_id: int, student_id: int) -> bool:
    """เช็คว่านักเรียนอยู่ใน classroom แล้วหรือยัง"""
    return ( db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
    ).first()
    )

def get_classroon_member(db: Session, classroom_id: int) -> list[ClassroomMember]:
    return(db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).all()
    )
    
def get_classrooms_by_code(db: Session, code: str):
    return (
        db.query(Classroom)
        .filter(
           Classroom.code == code,
           Classroom.deleted_date.is_(None)
        )
        .first()
    )

def delete_classroom_member(db: Session, classroom_id: int, student_id: int):
    member = db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
    ).first()
    if member:
        db.delete(member)
        db.flush()           # send DELETE to DB but keep transaction open
        db.expunge(member)   # detach object so it survives after commit
        db.commit()
        return member        # now safe to read fields after commit
    return None