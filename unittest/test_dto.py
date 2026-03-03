"""
Tests: DTO / Schema validation
ครอบคลุม: CreateClassroomRequest, LoginRequest, CreateStudentRequest, CreateTeacherRequest
"""
import pytest
from pydantic import ValidationError


# ─────────────────────────────────────────────
# Classroom DTOs
# ─────────────────────────────────────────────
class TestCreateClassroomRequest:
    def test_valid_data(self):
        from app.core.classroom.dto import CreateClassroomRequest
        data = CreateClassroomRequest(name="Math 101", semester="1/2025")
        assert data.name == "Math 101"
        assert data.semester == "1/2025"
        assert data.description is None

    def test_with_description(self):
        from app.core.classroom.dto import CreateClassroomRequest
        data = CreateClassroomRequest(name="Math", semester="1/2025", description="Advanced Math")
        assert data.description == "Advanced Math"

    def test_missing_name_raises(self):
        from app.core.classroom.dto import CreateClassroomRequest
        with pytest.raises(ValidationError):
            CreateClassroomRequest(semester="1/2025")

    def test_missing_semester_raises(self):
        from app.core.classroom.dto import CreateClassroomRequest
        with pytest.raises(ValidationError):
            CreateClassroomRequest(name="Math")


class TestCreateClassroomResponse:
    def test_valid(self):
        from app.core.classroom.dto import CreateClassroomResponse
        resp = CreateClassroomResponse(id=1, name="Math", code="ABC12345", semester="1/2025", teacher_id=10)
        assert resp.id == 1
        assert resp.code == "ABC12345"


# ─────────────────────────────────────────────
# Auth DTOs
# ─────────────────────────────────────────────
class TestLoginRequest:
    def test_valid(self):
        from app.core.auth.dto import LoginRequest
        req = LoginRequest(email="user@test.com", password="secret")
        assert req.email == "user@test.com"

    def test_missing_fields(self):
        from app.core.auth.dto import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="user@test.com")


class TestTokenDTO:
    def test_default_token_type(self):
        from app.core.auth.dto import Token
        token = Token(access_token="abc123")
        assert token.token_type == "bearer"

    def test_custom_token(self):
        from app.core.auth.dto import Token
        token = Token(access_token="xyz", token_type="bearer")
        assert token.access_token == "xyz"


# ─────────────────────────────────────────────
# Student DTOs
# ─────────────────────────────────────────────
class TestCreateStudentRequest:
    def test_valid(self):
        from app.core.student.dto import CreateStudentRequest
        req = CreateStudentRequest(
            first_name="Bob",
            last_name="Lee",
            email="bob@test.com",
            password="pass123",
            academy="MIT",
            student_id="STU001",
        )
        assert req.email == "bob@test.com"

    def test_invalid_email(self):
        from app.core.student.dto import CreateStudentRequest
        with pytest.raises(ValidationError):
            CreateStudentRequest(
                first_name="Bob",
                last_name="Lee",
                email="not-an-email",
                password="pass123",
                academy="MIT",
                student_id="STU001",
            )

    def test_missing_required_field(self):
        from app.core.student.dto import CreateStudentRequest
        with pytest.raises(ValidationError):
            CreateStudentRequest(email="bob@test.com", password="pass123")


# ─────────────────────────────────────────────
# Admin DTOs
# ─────────────────────────────────────────────
class TestCreateAdminRequest:
    def test_valid(self):
        from app.core.admin.dto import CreateAdminRequest
        req = CreateAdminRequest(email="admin@test.com", password="adminpass")
        assert req.email == "admin@test.com"

    def test_invalid_email(self):
        from app.core.admin.dto import CreateAdminRequest
        with pytest.raises(ValidationError):
            CreateAdminRequest(email="bad-email", password="adminpass")