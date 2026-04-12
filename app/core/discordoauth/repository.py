from sqlalchemy.orm import Session
from app.models.schema import Student


def get_student_by_user_id(db: Session, user_id: int) -> Student | None:
    return db.query(Student).filter(Student.user_id == user_id).first()


def get_student_by_discord_user_id(
    db: Session, discord_user_id: str
) -> Student | None:
    return (
        db.query(Student)
        .filter(Student.discord_user_id == discord_user_id)
        .first()
    )


def link_discord_user(
    db: Session, user_id: int, discord_user_id: str
) -> Student | None:
    student = get_student_by_user_id(db, user_id)
    if not student:
        return None

    student.discord_user_id = discord_user_id
    db.commit()
    db.refresh(student)
    return student