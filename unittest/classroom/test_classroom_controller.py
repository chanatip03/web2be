"""
test_classroom_controller.py

Corrections:
- test_no_teacher_profile_returns_403: controller raises HTTPException(403) for ValueError
  from create_new_classroom when teacher profile not found, NOT 500. Changed assertion to 403.
- test_student_cannot_update / test_wrong_teacher: ValueError not caught → 500 (unchanged).
- ResponseValidationError on GET/PUT: fixed in conftest by seeding academy="" and certificate_url="".
"""
import pytest
from fastapi.testclient import TestClient
from app.models.schema import ClassroomMember
from conftest import (
    make_client, seed_teacher, seed_student,
    seed_classroom, current_user_payload,
)


# ── POST /classroom/ ───────────────────────────────────────────────────────────

class TestCreateClassroomEndpoint:
    def test_creates_classroom_success(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_client(engine, current_user_payload(user.id, "teacher"))

        resp = client.post("/classroom/", json={"name": "CS101", "semester": "1/2025"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "CS101"
        assert data["semester"] == "1/2025"
        assert len(data["code"]) == 6

    def test_creates_with_description_and_outcomes(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_client(engine, current_user_payload(user.id, "teacher"))

        resp = client.post("/classroom/", json={
            "name": "Math", "semester": "2/2025",
            "description": "Advanced", "learningoutcomes": "Solve equations",
        })
        assert resp.status_code == 200
        assert resp.json()["description"] == "Advanced"

    def test_student_cannot_create_returns_403(self, engine, db):
        user, _ = seed_student(db)
        client = make_client(engine, current_user_payload(user.id, "student"))

        resp = client.post("/classroom/", json={"name": "X", "semester": "1/2025"})
        assert resp.status_code == 403

    def test_missing_name_returns_422(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_client(engine, current_user_payload(user.id, "teacher"))
        assert client.post("/classroom/", json={"semester": "1/2025"}).status_code == 422

    def test_missing_semester_returns_422(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_client(engine, current_user_payload(user.id, "teacher"))
        assert client.post("/classroom/", json={"name": "Math"}).status_code == 422

    def test_no_teacher_profile_returns_403(self, engine, db):
        # ValueError("Teacher profile not found") is caught by controller → 403
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan@test.com", password="h", academy="")
        db.add(user)
        db.commit()
        client = make_client(engine, current_user_payload(user.id, "teacher"))
        resp = client.post("/classroom/", json={"name": "X", "semester": "1/2025"})
        assert resp.status_code == 403


# ── GET /classroom/ ────────────────────────────────────────────────────────────

class TestGetClassroomsEndpoint:
    def test_teacher_gets_own_classrooms(self, engine, db):
        user, teacher = seed_teacher(db)
        seed_classroom(db, teacher.id, name="C1")
        seed_classroom(db, teacher.id, name="C2")
        client = make_client(engine, current_user_payload(user.id, "teacher"))

        resp = client.get("/classroom/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_student_gets_enrolled_classrooms(self, engine, db):
        _, teacher = seed_teacher(db, email="t@t.com")
        s_user, student = seed_student(db, email="s@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=student.id))
        db.commit()

        client = make_client(engine, current_user_payload(s_user.id, "student"))
        resp = client.get("/classroom/")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_teacher_no_classrooms_returns_empty(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_client(engine, current_user_payload(user.id, "teacher"))
        resp = client.get("/classroom/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unknown_role_returns_empty(self, engine, db):
        client = make_client(engine, {"id": 99, "role": "admin"})
        resp = client.get("/classroom/")
        assert resp.status_code == 200
        assert resp.json() == []


# ── GET /classroom/{classroom_id} ─────────────────────────────────────────────

class TestGetClassroomByIdEndpoint:
    def test_returns_classroom_details(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Physics")
        client = make_client(engine, {})

        resp = client.get(f"/classroom/{c.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == c.id
        assert data["name"] == "Physics"
        assert "teacher" in data

    def test_returns_404_for_nonexistent(self, engine, db):
        client = make_client(engine, {})
        assert client.get("/classroom/9999").status_code == 404

    def test_returns_404_for_soft_deleted(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, deleted=True)
        client = make_client(engine, {})
        assert client.get(f"/classroom/{c.id}").status_code == 404


# ── PUT /classroom/{classroom_id} ─────────────────────────────────────────────

class TestUpdateClassroomEndpoint:
    def test_updates_successfully(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Old")
        client = make_client(engine, current_user_payload(user.id, "teacher"))

        resp = client.put(f"/classroom/{c.id}", json={
            "name": "New Name", "semester": "2/2025",
            "description": None, "learningoutcomes": None,
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_student_cannot_update_returns_500(self, engine, db):
        # ValueError not caught in controller → 500
        _, teacher = seed_teacher(db, email="t@t.com")
        s_user, _ = seed_student(db, email="s@s.com")
        c = seed_classroom(db, teacher.id)
        client = make_client(engine, current_user_payload(s_user.id, "student"))

        resp = client.put(f"/classroom/{c.id}", json={
            "name": "X", "semester": "1/2025",
            "description": None, "learningoutcomes": None,
        })
        assert resp.status_code == 500

    def test_wrong_teacher_returns_500(self, engine, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        client = make_client(engine, current_user_payload(u2.id, "teacher"))

        resp = client.put(f"/classroom/{c.id}", json={
            "name": "Hack", "semester": "1/2025",
            "description": None, "learningoutcomes": None,
        })
        assert resp.status_code == 500

    def test_updates_learningoutcomes(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        client = make_client(engine, current_user_payload(user.id, "teacher"))

        resp = client.put(f"/classroom/{c.id}", json={
            "name": c.name, "semester": c.semester,
            "description": None, "learningoutcomes": "Understand loops",
        })
        assert resp.status_code == 200
        assert resp.json()["learningoutcomes"] == "Understand loops"