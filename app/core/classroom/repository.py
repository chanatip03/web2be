from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.models.schema import Classroom, ClassroomMember, LearningOutcome, Student, Teacher, User

def get_students_query(db: Session, classroom_id: int, search: str | None):
    query = (
        db.query(Student)
        .options(joinedload(Student.user))
        .join(ClassroomMember, ClassroomMember.student_id == Student.id)
        .filter(
            ClassroomMember.classroom_id == classroom_id,
            ClassroomMember.deleted_date.is_(None)
        )
    )

    if search:
        query = query.join(User).filter(
            (User.first_name.ilike(f"%{search}%")) |
            (User.last_name.ilike(f"%{search}%"))
        )

    return query

def count_students(db: Session, classroom_id: int):
    return (
        db.query(func.count(ClassroomMember.id))
        .filter(
            ClassroomMember.classroom_id == classroom_id,
            ClassroomMember.deleted_date.is_(None)
        )
        .scalar()
    )