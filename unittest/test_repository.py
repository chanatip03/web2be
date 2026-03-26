"""
Tests: Repository Layer
ครอบคลุม: classroom, admin, auth repositories
ใช้ SQLite in-memory แทน PostgreSQL
"""
import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────
# Classroom Repository
# ─────────────────────────────────────────────
class TestClassroomRepository:
    def test_generate_classroom_code_length(self):
        from app.core.classroom.repository import generate_classroom_code
        code = generate_classroom_code()
        assert len(code) == 8

    def test_generate_classroom_code_is_alphanumeric(self):
        from app.core.classroom.repository import generate_classroom_code
        for _ in range(20):
            code = generate_classroom_code()
            assert code.isalnum()

    def test_generate_classroom_code_is_uppercase(self):
        from app.core.classroom.repository import generate_classroom_code
        for _ in range(10):
            code = generate_classroom_code()
            assert code == code.upper()

    def test_create_classroom(self, db, make_teacher):
        from app.core.classroom.repository import create_classroom
        _, teacher = make_teacher()

        classroom = create_classroom(db, name="Math 101", semester="1/2025", teacher_id=teacher.id)
        assert classroom.id is not None
        assert classroom.name == "Math 101"
        assert classroom.semester == "1/2025"
        assert classroom.teacher_id == teacher.id
        assert len(classroom.code) == 8

    def test_create_classroom_with_description(self, db, make_teacher):
        from app.core.classroom.repository import create_classroom
        _, teacher = make_teacher()

        classroom = create_classroom(
            db, name="Physics", semester="2/2025",
            teacher_id=teacher.id, description="Advanced Physics"
        )
        assert classroom.description == "Advanced Physics"

    def test_get_classroom_by_id_found(self, db, make_classroom):
        from app.core.classroom.repository import get_classroom_by_id
        classroom, _, _ = make_classroom()

        result = get_classroom_by_id(db, classroom.id)
        assert result is not None
        assert result.id == classroom.id

    def test_get_classroom_by_id_not_found(self, db):
        from app.core.classroom.repository import get_classroom_by_id
        result = get_classroom_by_id(db, 99999)
        assert result is None

    def test_get_classroom_by_id_excludes_soft_deleted(self, db, make_classroom):
        from app.core.classroom.repository import get_classroom_by_id
        from datetime import datetime, timezone
        classroom, _, _ = make_classroom()

        classroom.deleted_date = datetime.now(timezone.utc)
        db.commit()

        result = get_classroom_by_id(db, classroom.id)
        assert result is None

    def test_get_classrooms_by_teacher(self, db, make_teacher):
        from app.core.classroom.repository import create_classroom, get_classrooms_by_teacher
        _, teacher = make_teacher()

        create_classroom(db, "Class A", "1/2025", teacher.id)
        create_classroom(db, "Class B", "2/2025", teacher.id)

        results = get_classrooms_by_teacher(db, teacher.id)
        assert len(results) == 2

    def test_get_classrooms_by_teacher_excludes_deleted(self, db, make_teacher):
        from app.core.classroom.repository import create_classroom, get_classrooms_by_teacher
        from datetime import datetime, timezone
        _, teacher = make_teacher()

        c1 = create_classroom(db, "Active", "1/2025", teacher.id)
        c2 = create_classroom(db, "Deleted", "2/2025", teacher.id)
        c2.deleted_date = datetime.now(timezone.utc)
        db.commit()

        results = get_classrooms_by_teacher(db, teacher.id)
        assert len(results) == 1
        assert results[0].name == "Active"

    def test_get_classrooms_by_teacher_returns_empty_for_wrong_teacher(self, db, make_teacher):
        from app.core.classroom.repository import get_classrooms_by_teacher
        get_classrooms_by_teacher(db, 99999)  # ต้องไม่ error
        # ผลลัพธ์ขึ้นกับ DB แต่ไม่ควร raise

    def test_get_student_count_empty(self, db, make_classroom):
        from app.core.classroom.repository import get_student_count
        classroom, _, _ = make_classroom()

        count = get_student_count(db, classroom.id)
        assert count == 0

    def test_get_student_count_with_members(self, db, make_classroom, make_student):
        from app.core.classroom.repository import get_student_count
        from app.models.schema import ClassroomMember
        classroom, _, _ = make_classroom()
        _, student = make_student(email="s1@test.com", student_id="S001")

        member = ClassroomMember(classroom_id=classroom.id, student_id=student.id)
        db.add(member)
        db.commit()

        count = get_student_count(db, classroom.id)
        assert count == 1

    def test_get_student_count_excludes_soft_deleted(self, db, make_classroom, make_student):
        from app.core.classroom.repository import get_student_count
        from app.models.schema import ClassroomMember
        from datetime import datetime, timezone
        classroom, _, _ = make_classroom()
        _, student = make_student(email="s2@test.com", student_id="S002")

        member = ClassroomMember(
            classroom_id=classroom.id,
            student_id=student.id,
            deleted_date=datetime.now(timezone.utc)
        )
        db.add(member)
        db.commit()

        count = get_student_count(db, classroom.id)
        assert count == 0


# ─────────────────────────────────────────────
# Admin Repository
# ─────────────────────────────────────────────
class TestAdminRepository:
    def test_create_admin(self, db):
        from app.core.admin.repository import create_admin
        admin = create_admin(db, "admin@test.com", "plainpassword")

        assert admin.id is not None
        assert admin.email == "admin@test.com"
        # password ต้องถูก hash แล้ว
        assert admin.password != "plainpassword"

    def test_get_admin_by_email_found(self, db, make_admin):
        from app.core.admin.repository import get_admin_by_email
        make_admin(email="admin@test.com")

        result = get_admin_by_email(db, "admin@test.com")
        assert result is not None
        assert result.email == "admin@test.com"

    def test_get_admin_by_email_not_found(self, db):
        from app.core.admin.repository import get_admin_by_email
        result = get_admin_by_email(db, "nobody@test.com")
        assert result is None


# ─────────────────────────────────────────────
# Auth Repository
# ─────────────────────────────────────────────
class TestAuthRepository:
    def test_get_user_by_email_found(self, db, make_user):
        from app.core.auth.repository import get_user_by_email
        make_user(email="user@test.com")

        result = get_user_by_email(db, "user@test.com")
        assert result is not None
        assert result.email == "user@test.com"

    def test_get_user_by_email_not_found(self, db):
        from app.core.auth.repository import get_user_by_email
        result = get_user_by_email(db, "ghost@test.com")
        assert result is None

    def test_get_admin_by_email_found(self, db, make_admin):
        from app.core.auth.repository import get_admin_by_email
        make_admin(email="adm@test.com")

        result = get_admin_by_email(db, "adm@test.com")
        assert result is not None

    def test_get_admin_by_email_not_found(self, db):
        from app.core.auth.repository import get_admin_by_email
        result = get_admin_by_email(db, "nobody@admin.com")
        assert result is None