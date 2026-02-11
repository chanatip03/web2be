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
        )
        .all()
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

def is_student_in_classroom(db: Session, classroom_id: int, student_id: int) -> bool:
    """เช็คว่านักเรียนอยู่ใน classroom แล้วหรือยัง"""
    return ( db.query(ClassroomMember).filter(
        ClassroomMember.classroom_id == classroom_id,
        ClassroomMember.student_id == student_id,
        ClassroomMember.deleted_date.is_(None)
    ).first()
    )


def add_student_to_classroom(db: Session, member: ClassroomMember) -> ClassroomMember:
    db.add(member)
    db.commit()
    db.refresh(member)
    return member
