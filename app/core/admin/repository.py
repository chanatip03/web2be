from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.schema import Admin
from app.models.schema import Role, Student, Teacher, User
from app.utils.generate_token import hash_password

def create_admin(db: Session, email: str, password: str):
    try:
        admin = Admin(
            email=email,
            password=hash_password(password),
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin
    except Exception:
        db.rollback()
        raise

def get_admin_by_email(db: Session, email: str):
    return db.query(Admin).filter(Admin.email == email).first()


def get_student_users(db: Session, search: str | None = None):
    query = (
        db.query(User)
        .join(Role)
        .join(Student)
        .options(joinedload(User.student))
        .filter(
            Role.name == "student",
            User.deleted_date.is_(None),
            Student.deleted_date.is_(None),
        )
    )

    if search:
        keyword = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.first_name.ilike(keyword),
                User.last_name.ilike(keyword),
                User.email.ilike(keyword),
                User.academy.ilike(keyword),
                Student.student_id.ilike(keyword),
            )
        )

    return query.order_by(User.created_date.desc()).all()


def get_students_by_ids(db: Session, student_ids: list[int]) -> dict[int, Student]:
    if not student_ids:
        return {}

    students = (
        db.query(Student)
        .filter(
            Student.id.in_(student_ids),
            Student.deleted_date.is_(None),
        )
        .all()
    )
    return {student.id: student for student in students}


def get_teacher_users(db: Session, search: str | None = None, *, approved_only: bool | None = None):
    query = (
        db.query(User)
        .join(Role)
        .join(Teacher)
        .options(joinedload(User.teacher))
        .filter(
            Role.name == "teacher",
            User.deleted_date.is_(None),
            Teacher.deleted_date.is_(None),
        )
    )

    if approved_only is not None:
        query = query.filter(Teacher.is_approved.is_(approved_only))

    if search:
        keyword = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.first_name.ilike(keyword),
                User.last_name.ilike(keyword),
                User.email.ilike(keyword),
                User.academy.ilike(keyword),
            )
        )

    return query.order_by(User.created_date.desc()).all()


def get_teacher_request_user(db: Session, user_id: int):
    return (
        db.query(User)
        .join(Teacher)
        .options(joinedload(User.teacher))
        .filter(
            User.id == user_id,
            User.deleted_date.is_(None),
            Teacher.deleted_date.is_(None),
            Teacher.is_approved.is_(False),
        )
        .first()
    )


def set_teacher_approval(db: Session, teacher: Teacher, is_approved: bool):
    teacher.is_approved = is_approved
    db.commit()
    db.refresh(teacher)
    return teacher


def delete_pending_teacher_request(db: Session, user: User) -> None:
    db.delete(user)
    db.commit()
