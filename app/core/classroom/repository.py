from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.models.schema import Classroom, ClassroomMember, LearningOutcome, Student, Teacher, User


def get_classroom_if_teacher(db: Session, classroom_id: int, teacher_id: int):
    return db.query(Classroom).filter(
        Classroom.id == classroom_id,
        Classroom.teacher_id == teacher_id,
        Classroom.deleted_date.is_(None)
    ).first()


def get_classroom_for_syllabus(db: Session, classroom_id: int, teacher_id: int):
    return (
        db.query(Classroom)
        .options(
            joinedload(Classroom.teacher).joinedload("user"),
            joinedload(Classroom.learning_outcomes)
        )
        .filter(
            Classroom.id == classroom_id,
            Classroom.teacher_id == teacher_id,
            Classroom.deleted_date.is_(None)
        )
        .first()
    )

def get_teacher_by_user_id(db: Session, user_id: int):
    return db.query(Teacher).filter(
        Teacher.user_id == user_id,
        Teacher.deleted_date.is_(None)
    ).first()