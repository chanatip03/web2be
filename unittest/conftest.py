"""
conftest.py

KEY FIXES:
1. StaticPool: all connections share one SQLite in-memory database
2. seed_user: include `academy=""` — ClassroomResponse.teacher.user.academy is `str` not Optional[str],
   so None causes ResponseValidationError when FastAPI serializes the response
3. seed_teacher: include `certificate_url=""` — same reason, ClassroomResponse.teacher.certificate_url is str
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.database import Base, get_db
from app.utils.validator import get_current_user
from app.models.schema import User, Teacher, Student, Classroom, ClassroomMember
from app.core.classroom.controller import router


@pytest.fixture(scope="function")
def engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture(scope="function")
def db(engine):
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()


def make_client(engine, current_user_data: dict) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user_data
    return TestClient(app)


def seed_user(db, email="user@test.com", first_name="Alice", last_name="Smith"):
    user = User(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password="hashed",
        academy="",          # ClassroomResponse.teacher.user.academy: str (not Optional)
    )
    db.add(user)
    db.flush()
    db.refresh(user)
    return user


def seed_teacher(db, email="teacher@test.com"):
    user = seed_user(db, email=email)
    teacher = Teacher(
        user_id=user.id,
        certificate_url="",  # ClassroomResponse.teacher.certificate_url: str (not Optional)
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return user, teacher


def seed_student(db, email="student@test.com"):
    user = seed_user(db, email=email, first_name="Bob", last_name="Jones")
    student = Student(user_id=user.id)
    db.add(student)
    db.commit()
    db.refresh(student)
    return user, student


def seed_classroom(db, teacher_id, name="CS101", semester="1/2025", deleted=False):
    c = Classroom(
        name=name,
        code=f"{name[:3].upper()}{teacher_id}",
        semester=semester,
        teacher_id=teacher_id,
        deleted_date=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def current_user_payload(user_id: int, role: str) -> dict:
    return {"id": user_id, "role": role}