"""
Shared fixtures สำหรับ unit tests ทั้งหมด
"""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("HASH_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("SUBMISSIONS_DIR", "/tmp/submissions")
os.environ.setdefault("RESULTS_DIR", "/tmp/results")

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.models.schema import Base, User, Teacher, Student, Role, Classroom, ClassroomMember, RoleEnum, Admin


# ─────────────────────────────────────────────
# In-memory SQLite engine สำหรับ test
# ─────────────────────────────────────────────
@pytest.fixture(scope="function")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture(scope="function")
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ─────────────────────────────────────────────
# Helper: สร้าง User จริงใน DB
# ─────────────────────────────────────────────
@pytest.fixture
def make_user(db):
    def _make(
        first_name="John",
        last_name="Doe",
        email="john@test.com",
        password="hashed_pw",
        academy="TestU",
    ):
        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password,
            academy=academy,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return _make


@pytest.fixture
def make_teacher(db, make_user):
    def _make(email="teacher@test.com", first_name="Alice", last_name="Smith"):
        user = make_user(first_name=first_name, last_name=last_name, email=email)
        teacher = Teacher(user_id=user.id, certificate_url="https://example.com/cert.pdf")
        db.add(teacher)
        db.commit()
        db.refresh(teacher)
        return user, teacher
    return _make


@pytest.fixture
def make_student(db, make_user):
    def _make(email="student@test.com", student_id="STU001"):
        user = make_user(email=email, first_name="Bob", last_name="Lee")
        student = Student(user_id=user.id, student_id=student_id)
        db.add(student)
        db.commit()
        db.refresh(student)
        return user, student
    return _make


@pytest.fixture
def make_classroom(db, make_teacher):
    def _make(name="Test Class", semester="1/2025", code="ABCD1234"):
        user, teacher = make_teacher()
        classroom = Classroom(
            name=name,
            code=code,
            semester=semester,
            description="Test description",
            teacher_id=teacher.id,
        )
        db.add(classroom)
        db.commit()
        db.refresh(classroom)
        return classroom, teacher, user
    return _make


@pytest.fixture
def make_admin(db):
    def _make(email="admin@test.com", password="hashed_pw"):
        admin = Admin(email=email, password=password)
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin
    return _make


# ─────────────────────────────────────────────
# FastAPI TestClient
# ─────────────────────────────────────────────
@pytest.fixture
def client(db):
    from fastapi import FastAPI
    from app.core import api_router
    from app.db.database import get_db
    from starlette.testclient import TestClient

    application = FastAPI()
    application.include_router(api_router, prefix="/api")

    # ใช้ session เดียวกับ db fixture → tables ถูกสร้างแล้ว
    application.dependency_overrides[get_db] = lambda: db

    with TestClient(application) as c:
        yield c