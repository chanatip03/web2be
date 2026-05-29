from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload
from app.models.schema import Classroom, Teacher, ClassroomMember, Student

def create_classroom(db: Session, classroom: Classroom):
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom

def get_classroom_by_id(db: Session, classroom_id: int) -> Classroom | None:
    return (db.query(Classroom)
        .options(
            joinedload(Classroom.teacher)
            .joinedload(Teacher.user))
        .filter(
            Classroom.id == classroom_id,
            Classroom.deleted_date.is_(None)).first()
    )

def get_classrooms_by_teacher_id(db: Session, teacher_id: int):
    return (
        db.query(Classroom)
        .options(
        joinedload(Classroom.teacher)
        .joinedload(Teacher.user))
        .filter(
            Classroom.teacher_id == teacher_id,
            Classroom.deleted_date.is_(None)
        ).order_by(
            desc(Classroom.created_date)
        ).all()
    )

def get_classrooms_by_student_id(db: Session, student_id: int):
    return (
        db.query(Classroom)
        .join(ClassroomMember)
        .options(
        joinedload(Classroom.teacher)
        .joinedload(Teacher.user))
        .filter(
            ClassroomMember.student_id == student_id,
            Classroom.deleted_date.is_(None) 
        )
        .all()
    )

def get_student_count(db: Session, classroom_id: int) -> int:
    """นับจำนวนนักเรียนใน classroom"""
    return db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.deleted_date.is_(None)
    ).count()

def get_classroom_members(db: Session, classroom_id: int) -> ClassroomMember:
    return (
        db.query(ClassroomMember)
        .options(
            joinedload(ClassroomMember.student)
            .joinedload(Student.user)
        )
        .filter(
            ClassroomMember.classroom_id == classroom_id,
            ClassroomMember.deleted_date.is_(None),
        )
        .all()
    )

def is_classroom_of_teacher(db: Session, classroom_id: int, teacher_id: int) -> bool:

    return ( db.query(Classroom).filter(
        Classroom.id == classroom_id,
        Classroom.teacher_id == teacher_id,
        Classroom.deleted_date.is_(None)
    ).first()
    )

def update_classroom(db: Session, classroom: Classroom, update_data: dict) -> Classroom:
    for key, value in update_data.items():
        if value is not None:
            setattr(classroom, key, value)

    db.commit()
    db.refresh(classroom)
    return classroom

