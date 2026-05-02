from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.schema import Admin
from app.models.schema import Student, Teacher, User
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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _person_search_clause(search: str | None, fields: list[str]) -> tuple[str, dict]:
    if not search or not search.strip():
        return "", {}

    keyword = f"%{_escape_like(search.strip())}%"
    clauses = [f"{field} ILIKE :keyword ESCAPE '\\\\'" for field in fields]
    return f" AND ({' OR '.join(clauses)})", {"keyword": keyword}


def get_student_users(db: Session, search: str | None = None):
    search_clause, params = _person_search_clause(
        search,
        ["u.first_name", "u.last_name", "u.email", "COALESCE(u.academy, '')", "COALESCE(s.student_id, '')"],
    )

    rows = db.execute(
        text(
            f"""
            SELECT
                u.id,
                u.first_name,
                u.last_name,
                u.email,
                u.academy,
                u.image_url,
                s.student_id
            FROM users u
            JOIN students s ON s.user_id = u.id
            JOIN roles r ON r.id = u.role_id
            WHERE r.name = 'student'
              AND u.deleted_date IS NULL
              AND s.deleted_date IS NULL
              {search_clause}
            ORDER BY u.created_date DESC
            """
        ),
        params,
    ).mappings().all()

    return [SimpleNamespace(**row) for row in rows]


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
    search_clause, params = _person_search_clause(
        search,
        ["u.first_name", "u.last_name", "u.email", "COALESCE(u.academy, '')"],
    )

    approval_clause = ""
    if approved_only is True:
        approval_clause = " AND t.is_approved IS TRUE"
    elif approved_only is False:
        approval_clause = " AND COALESCE(t.is_approved, FALSE) IS FALSE"

    rows = db.execute(
        text(
            f"""
            SELECT
                u.id,
                u.first_name,
                u.last_name,
                u.email,
                u.academy,
                u.image_url,
                t.certificate_url,
                COALESCE(t.is_approved, FALSE) AS is_approved
            FROM users u
            JOIN teachers t ON t.user_id = u.id
            JOIN roles r ON r.id = u.role_id
            WHERE r.name = 'teacher'
              AND u.deleted_date IS NULL
              AND t.deleted_date IS NULL
              {approval_clause}
              {search_clause}
            ORDER BY u.created_date DESC
            """
        ),
        params,
    ).mappings().all()

    return [SimpleNamespace(**row) for row in rows]


def get_teacher_request_user(db: Session, user_id: int):
    row = db.execute(
        text(
            """
            SELECT
                u.id AS user_id,
                t.id AS teacher_id,
                COALESCE(t.is_approved, FALSE) AS is_approved
            FROM users u
            JOIN teachers t ON t.user_id = u.id
            WHERE u.id = :user_id
              AND u.deleted_date IS NULL
              AND t.deleted_date IS NULL
              AND COALESCE(t.is_approved, FALSE) IS FALSE
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    ).mappings().first()
    return SimpleNamespace(**row) if row else None


def set_teacher_approval(db: Session, teacher: Teacher, is_approved: bool):
    if hasattr(teacher, "teacher_id"):
        db.execute(
            text(
                """
                UPDATE teachers
                SET is_approved = :is_approved,
                    updated_date = NOW()
                WHERE id = :teacher_id
                """
            ),
            {"teacher_id": teacher.teacher_id, "is_approved": is_approved},
        )
        db.commit()
        return teacher

    teacher.is_approved = is_approved
    db.commit()
    db.refresh(teacher)
    return teacher


def delete_pending_teacher_request(db: Session, user: User) -> None:
    if hasattr(user, "user_id"):
        db.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user.user_id})
        db.commit()
        return

    db.delete(user)
    db.commit()
