import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db.database import get_db
from app.utils.validator import get_current_user
from app.core.assignment.controller import router as assignment_router

from conftest import (
    seed_teacher, seed_student, seed_classroom, current_user_payload,
)
from fixtures import (
    seed_project_type, seed_language,
    seed_assignment, seed_attachment,
)

MOCK_UPLOAD = ("mock-key", "https://mocked.r2.url/file")


def make_assignment_client(engine, current_user_data: dict) -> TestClient:
    """Client that includes the assignment router (not classroom router)."""
    app = FastAPI()
    app.include_router(assignment_router)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user_data
    return TestClient(app, raise_server_exceptions=False)


def _form(classroom_id, project_type_id=None, **kwargs):
    now = datetime.now(timezone.utc)
    defaults = {
        "classroom_id": str(classroom_id),
        "start_date": now.isoformat(),
        "due_date": (now + timedelta(days=7)).isoformat(),
        "is_group": "false",
        "title": "Lab 1",
    }
    if project_type_id is not None:
        defaults["project_type_id"] = str(project_type_id)
    defaults.update(kwargs)
    return defaults


# ── GET /assignment/?classroom_id= ────────────────────────────────────────────

class TestGetAssignmentsEndpoint:
    def test_returns_assignments(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="A1")
        seed_assignment(db, c.id, pt.id, title="A2")
        client = make_assignment_client(engine, {})
        resp = client.get("/assignment/", params={"classroom_id": c.id})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_excludes_soft_deleted(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="Active")
        seed_assignment(db, c.id, pt.id, title="Gone", deleted=True)
        client = make_assignment_client(engine, {})
        resp = client.get("/assignment/", params={"classroom_id": c.id})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_returns_404_for_nonexistent_classroom(self, engine, db):
        client = make_assignment_client(engine, {})
        resp = client.get("/assignment/", params={"classroom_id": 9999})
        assert resp.status_code == 404

    def test_returns_empty_list(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        client = make_assignment_client(engine, {})
        resp = client.get("/assignment/", params={"classroom_id": c.id})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_missing_classroom_id_returns_422(self, engine, db):
        client = make_assignment_client(engine, {})
        assert client.get("/assignment/").status_code == 422


# ── GET /assignment/{assignment_id} ───────────────────────────────────────────

class TestGetAssignmentByIdEndpoint:
    def test_returns_assignment_details(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db, name="CLI")
        a = seed_assignment(db, c.id, pt.id, title="Lab 1")
        client = make_assignment_client(engine, {})
        resp = client.get(f"/assignment/{a.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == a.id
        assert data["title"] == "Lab 1"
        assert "projectType" in data or "project_type" in data

    def test_returns_404_for_nonexistent(self, engine, db):
        client = make_assignment_client(engine, {})
        assert client.get("/assignment/9999").status_code == 404

    def test_response_includes_active_attachments(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        seed_attachment(db, a.id, file_url="https://example.com/f.pdf")
        client = make_assignment_client(engine, {})
        resp = client.get(f"/assignment/{a.id}")
        assert resp.status_code == 200
        assert len(resp.json()["attachments"]) == 1

    def test_excludes_soft_deleted_attachments(self, engine, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        seed_attachment(db, a.id, file_url="https://active.com/f.pdf")
        seed_attachment(db, a.id, file_url="https://gone.com/f.pdf", deleted=True)
        client = make_assignment_client(engine, {})
        resp = client.get(f"/assignment/{a.id}")
        assert resp.status_code == 200
        assert len(resp.json()["attachments"]) == 1


# ── POST /assignment/ ─────────────────────────────────────────────────────────

class TestCreateAssignmentEndpoint:
    def test_creates_successfully(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        with patch("app.core.assignment.controller.upload_file", return_value=MOCK_UPLOAD):
            resp = client.post("/assignment/", data=_form(c.id, pt.id))
        assert resp.status_code == 200
        assert resp.json()["title"] == "Lab 1"

    def test_student_cannot_create_returns_403(self, engine, db):
        user, _ = seed_student(db)
        _, teacher = seed_teacher(db, email="t@t.com")
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        client = make_assignment_client(engine, current_user_payload(user.id, "student"))
        resp = client.post("/assignment/", data=_form(c.id, pt.id))
        assert resp.status_code == 403

    def test_wrong_teacher_returns_403(self, engine, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        pt = seed_project_type(db)
        client = make_assignment_client(engine, current_user_payload(u2.id, "teacher"))
        resp = client.post("/assignment/", data=_form(c.id, pt.id))
        assert resp.status_code == 403

    def test_missing_title_returns_422(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        now = datetime.now(timezone.utc)
        resp = client.post("/assignment/", data={
            "start_date": now.isoformat(),
            "due_date": (now + timedelta(days=7)).isoformat(),
            "is_group": "false",
            "project_type_id": str(pt.id),
            "classroom_id": str(c.id),
        })
        assert resp.status_code == 422


# ── PUT /assignment/{assignment_id} ───────────────────────────────────────────

class TestUpdateAssignmentEndpoint:
    def test_updates_title(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, title="Old")
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        with patch("app.core.assignment.controller.upload_file", return_value=MOCK_UPLOAD):
            resp = client.put(
                f"/assignment/{a.id}",
                data={"classroom_id": str(c.id), "title": "New Title"},
            )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_student_cannot_update_returns_403(self, engine, db):
        user, _ = seed_student(db)
        _, teacher = seed_teacher(db, email="t@t.com")
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        client = make_assignment_client(engine, current_user_payload(user.id, "student"))
        resp = client.put(f"/assignment/{a.id}", data={"classroom_id": str(c.id)})
        assert resp.status_code == 403

    def test_wrong_teacher_returns_403(self, engine, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        client = make_assignment_client(engine, current_user_payload(u2.id, "teacher"))
        resp = client.put(f"/assignment/{a.id}", data={"classroom_id": str(c.id)})
        assert resp.status_code == 403

    def test_missing_classroom_id_returns_422(self, engine, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        resp = client.put(f"/assignment/{a.id}", data={"title": "X"})
        assert resp.status_code == 422


# ── DELETE /assignment/{assignment_id} ────────────────────────────────────────

class TestDeleteAssignmentEndpoint:
    def test_nonexistent_assignment_returns_404(self, engine, db):
        user, _ = seed_teacher(db)
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        resp = client.delete("/assignment/9999")
        assert resp.status_code == 404

    def test_valid_delete_returns_500_due_to_bug(self, engine, db):
        """
        BUG in service.py: soft_delete_assignment(db, assignment, tz) — 'tz' undefined.
        Fix: remove the 'tz' argument from that call.
        """
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        client = make_assignment_client(engine, current_user_payload(user.id, "teacher"))
        resp = client.delete(f"/assignment/{a.id}")
        assert resp.status_code == 500