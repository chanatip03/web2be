"""
Tests: Service Layer
ครอบคลุม: classroom service, auth service, admin service, student/teacher service
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


# ─────────────────────────────────────────────
# Classroom Service
# ─────────────────────────────────────────────
class TestClassroomService:
    def test_create_new_classroom_success(self, db, make_teacher):
        from app.core.classroom.service import create_new_classroom
        user, teacher = make_teacher(email="teach@test.com")

        classroom = create_new_classroom(
            db=db,
            user_id=user.id,
            name="Math 101",
            semester="1/2025",
        )
        assert classroom.name == "Math 101"
        assert classroom.teacher_id == teacher.id
        assert len(classroom.code) == 8

    def test_create_new_classroom_not_a_teacher_raises(self, db, make_user):
        from app.core.classroom.service import create_new_classroom
        user = make_user(email="student@test.com")

        with pytest.raises(ValueError, match="not a teacher"):
            create_new_classroom(db=db, user_id=user.id, name="Class", semester="1/2025")

    def test_create_new_classroom_user_not_exist_raises(self, db):
        from app.core.classroom.service import create_new_classroom

        with pytest.raises(ValueError):
            create_new_classroom(db=db, user_id=99999, name="Class", semester="1/2025")

    def test_create_new_classroom_with_description(self, db, make_teacher):
        from app.core.classroom.service import create_new_classroom
        user, _ = make_teacher()

        classroom = create_new_classroom(
            db=db, user_id=user.id,
            name="Physics", semester="2/2025",
            description="Hard stuff"
        )
        assert classroom.description == "Hard stuff"

    def test_get_teacher_classrooms_success(self, db, make_teacher):
        from app.core.classroom.service import create_new_classroom, get_teacher_classrooms
        user, _ = make_teacher()
        create_new_classroom(db, user.id, "Class A", "1/2025")
        create_new_classroom(db, user.id, "Class B", "2/2025")

        results = get_teacher_classrooms(db, user.id)
        assert len(results) == 2

    def test_get_teacher_classrooms_not_teacher_returns_empty(self, db, make_user):
        from app.core.classroom.service import get_teacher_classrooms
        user = make_user(email="notteacher@test.com")

        results = get_teacher_classrooms(db, user.id)
        assert results == []

    def test_get_classroom_details_success(self, db, make_teacher):
        from app.core.classroom.service import create_new_classroom, get_classroom_details
        user, teacher = make_teacher(email="t2@test.com", first_name="Jane", last_name="Doe")

        classroom = create_new_classroom(db, user.id, "Bio", "1/2025")
        details = get_classroom_details(db, classroom.id, user.id)

        assert details is not None
        assert details["name"] == "Bio"
        assert details["teacher_name"] == "Jane Doe"
        assert details["student_count"] == 0
        assert "created_at" in details

    def test_get_classroom_details_not_found_returns_none(self, db, make_teacher):
        from app.core.classroom.service import get_classroom_details
        user, _ = make_teacher()

        result = get_classroom_details(db, 99999, user.id)
        assert result is None

    def test_get_classroom_details_wrong_teacher_returns_none(self, db, make_teacher):
        from app.core.classroom.service import create_new_classroom, get_classroom_details
        user1, _ = make_teacher(email="t3@test.com")
        user2, _ = make_teacher(email="t4@test.com")

        classroom = create_new_classroom(db, user1.id, "Chem", "1/2025")
        result = get_classroom_details(db, classroom.id, user2.id)
        assert result is None


# ─────────────────────────────────────────────
# Auth Service
# ─────────────────────────────────────────────
class TestAuthService:
    def test_authenticate_user_success(self, db):
        from app.core.auth.service import authenticate_user
        from app.utils.generate_token import hash_password
        from app.models.schema import User
        user = User(
            first_name="Test", last_name="User",
            email="auth@test.com",
            password=hash_password("correct_pass"),
            academy="Uni",
        )
        db.add(user)
        db.commit()

        result = authenticate_user(db, "auth@test.com", "correct_pass")
        assert result is not None
        assert result.email == "auth@test.com"

    def test_authenticate_user_wrong_password(self, db):
        from app.core.auth.service import authenticate_user
        from app.utils.generate_token import hash_password
        from app.models.schema import User
        user = User(
            first_name="T", last_name="U",
            email="wp@test.com",
            password=hash_password("correct"),
            academy="Uni",
        )
        db.add(user)
        db.commit()

        result = authenticate_user(db, "wp@test.com", "wrong")
        assert result is None

    def test_authenticate_user_not_found(self, db):
        from app.core.auth.service import authenticate_user
        result = authenticate_user(db, "nobody@test.com", "pass")
        assert result is None

    def test_authenticate_admin_success(self, db, make_admin):
        from app.core.auth.service import authenticate_admin
        from app.utils.generate_token import hash_password
        make_admin.__wrapped__ if hasattr(make_admin, '__wrapped__') else None

        # สร้าง admin ด้วย hash password จริง
        from app.models.schema import Admin
        admin = Admin(email="adm2@test.com", password=hash_password("admin_pass"))
        db.add(admin)
        db.commit()

        result = authenticate_admin(db, "adm2@test.com", "admin_pass")
        assert result is not None

    def test_authenticate_admin_not_found(self, db):
        from app.core.auth.service import authenticate_admin
        result = authenticate_admin(db, "nobody@admin.com", "pass")
        assert result is None

    def test_authenticate_admin_wrong_password(self, db):
        from app.core.auth.service import authenticate_admin
        from app.utils.generate_token import hash_password
        from app.models.schema import Admin
        admin = Admin(email="a3@test.com", password=hash_password("correct"))
        db.add(admin)
        db.commit()

        result = authenticate_admin(db, "a3@test.com", "wrong")
        assert result is None


# ─────────────────────────────────────────────
# Admin Service
# ─────────────────────────────────────────────
class TestAdminService:
    def test_create_admin_success(self, db):
        from app.core.admin.service import create_admin
        admin = create_admin(db, "newadmin@test.com", "password123")
        assert admin.email == "newadmin@test.com"
        assert admin.password != "password123"  # hashed

    def test_create_admin_duplicate_email_raises(self, db):
        from app.core.admin.service import create_admin
        create_admin(db, "dup@test.com", "pass1")

        with pytest.raises(HTTPException) as exc:
            create_admin(db, "dup@test.com", "pass2")
        assert exc.value.status_code == 400
        assert "already exists" in exc.value.detail


# ─────────────────────────────────────────────
# Student Service
# ─────────────────────────────────────────────
class TestStudentService:
    def test_create_student_success(self, db):
        from app.core.student.service import create_student
        user = create_student(
            db,
            first_name="Bob", last_name="Smith",
            email="bob@uni.com", password="pass123",
            academy="MIT", student_id="S001"
        )
        assert user.id is not None
        assert user.email == "bob@uni.com"
        # password ต้อง hash
        assert user.password != "pass123"

    def test_create_student_assigns_student_role(self, db):
        from app.core.student.service import create_student
        from app.models.schema import RoleEnum
        user = create_student(
            db, "Ann", "Jones", "ann@test.com", "pass", "UCLA", "S002"
        )
        role_names = [r.name for r in user.roles]
        assert RoleEnum.student in role_names

    def test_create_student_creates_profile(self, db):
        from app.core.student.service import create_student
        from app.models.schema import Student
        user = create_student(db, "Tom", "Brown", "tom@test.com", "pass", "Stanford", "S003")
        profile = db.query(Student).filter(Student.user_id == user.id).first()
        assert profile is not None
        assert profile.student_id == "S003"


# ─────────────────────────────────────────────
# Teacher Service
# ─────────────────────────────────────────────
class TestTeacherService:
    def test_create_teacher_success(self, db):
        from app.core.teacher.service import create_teacher
        user = create_teacher(
            db,
            first_name="Jane", last_name="Prof",
            email="prof@uni.com", password="securepass",
            academy="Harvard", certificate_url="https://example.com/cert.pdf"
        )
        assert user.id is not None
        assert user.email == "prof@uni.com"

    def test_create_teacher_assigns_teacher_role(self, db):
        from app.core.teacher.service import create_teacher
        from app.models.schema import RoleEnum
        user = create_teacher(
            db, "Dr", "Who", "drwho@test.com", "pass", "Oxford", "https://cert.url"
        )
        role_names = [r.name for r in user.roles]
        assert RoleEnum.teacher in role_names

    def test_create_teacher_creates_profile(self, db):
        from app.core.teacher.service import create_teacher
        from app.models.schema import Teacher
        user = create_teacher(
            db, "Prof", "X", "profx@test.com", "pass", "MIT", "https://cert.pdf"
        )
        profile = db.query(Teacher).filter(Teacher.user_id == user.id).first()
        assert profile is not None
        assert profile.certificate_url == "https://cert.pdf"

    def test_create_teacher_hashes_password(self, db):
        from app.core.teacher.service import create_teacher
        from app.utils.generate_token import verify_password
        user = create_teacher(
            db, "Ms", "Test", "ms@test.com", "mypassword", "Yale", "https://cert"
        )
        assert verify_password("mypassword", user.password)