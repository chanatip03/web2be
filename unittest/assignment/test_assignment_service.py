import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi import HTTPException

from app.core.assignment.service import (
    create_assignment_service,
    get_assignments_service,
    get_assignment_by_id_service,
    update_assignment_service,
    delete_assignment_service,
)
from app.core.assignment.dto import CreateAssignmentRequest, UpdateAssignmentRequest
from conftest import (
    seed_teacher, seed_student, seed_classroom, current_user_payload,
)
from fixtures import (
    seed_project_type, seed_language,
    seed_assignment, seed_attachment,
)

NOW = datetime.now(timezone.utc)
LATER = NOW + timedelta(days=7)


def _make_create(**kwargs):
    defaults = dict(
        title="Lab 1", start_date=NOW, due_date=LATER,
        is_group=False, project_type_id=None, classroom_id=None,
    )
    defaults.update(kwargs)
    return CreateAssignmentRequest(**defaults)


def _make_update(classroom_id, **kwargs):
    return UpdateAssignmentRequest(classroom_id=classroom_id, **kwargs)


# ── create_assignment_service ──────────────────────────────────────────────────

class TestCreateAssignmentService:
    def test_creates_for_teacher(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        data = _make_create(project_type_id=pt.id, classroom_id=c.id)
        result = create_assignment_service(
            data, None, [], db, current_user_payload(user.id, "teacher")
        )
        assert result.id is not None
        assert result.title == "Lab 1"
        assert result.classroom_id == c.id

    def test_creates_with_attachments(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        data = _make_create(project_type_id=pt.id, classroom_id=c.id)
        result = create_assignment_service(
            data, None, ["https://f1.com", "https://f2.com"],
            db, current_user_payload(user.id, "teacher")
        )
        assert len(result.attachments) == 2

    def test_creates_with_testcase_url(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        data = _make_create(project_type_id=pt.id, classroom_id=c.id)
        result = create_assignment_service(
            data, "https://tc.url", [], db, current_user_payload(user.id, "teacher")
        )
        assert result.testcase_url == "https://tc.url"

    def test_raises_for_student_role(self, db):
        user, _ = seed_student(db)
        data = _make_create(project_type_id=1, classroom_id=1)
        with pytest.raises(ValueError, match="Only teachers"):
            create_assignment_service(
                data, None, [], db, current_user_payload(user.id, "student")
            )

    def test_raises_http403_when_no_teacher_profile(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan@t.com", password="h")
        db.add(user); db.commit()
        data = _make_create(project_type_id=1, classroom_id=1)
        with pytest.raises(HTTPException) as exc:
            create_assignment_service(
                data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 403

    def test_raises_http404_for_nonexistent_classroom(self, db):
        user, _ = seed_teacher(db)
        pt = seed_project_type(db)
        data = _make_create(project_type_id=pt.id, classroom_id=9999)
        with pytest.raises(HTTPException) as exc:
            create_assignment_service(
                data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 404

    def test_raises_for_wrong_teacher(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        pt = seed_project_type(db)
        data = _make_create(project_type_id=pt.id, classroom_id=c.id)
        with pytest.raises(ValueError, match="not under"):
            create_assignment_service(
                data, None, [], db, current_user_payload(u2.id, "teacher")
            )

    def test_raises_http422_when_start_after_due(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        data = _make_create(
            project_type_id=pt.id, classroom_id=c.id,
            start_date=LATER, due_date=NOW,
        )
        with pytest.raises(HTTPException) as exc:
            create_assignment_service(
                data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 422


# ── get_assignments_service ────────────────────────────────────────────────────

class TestGetAssignmentsService:
    def test_returns_assignments(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="A1")
        seed_assignment(db, c.id, pt.id, title="A2")
        assert len(get_assignments_service(db, c.id)) == 2

    def test_raises_http404_for_nonexistent_classroom(self, db):
        with pytest.raises(HTTPException) as exc:
            get_assignments_service(db, 9999)
        assert exc.value.status_code == 404

    def test_returns_empty_list(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        assert get_assignments_service(db, c.id) == []

    def test_excludes_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="Active")
        seed_assignment(db, c.id, pt.id, title="Gone", deleted=True)
        result = get_assignments_service(db, c.id)
        assert len(result) == 1
        assert result[0].title == "Active"


# ── get_assignment_by_id_service ───────────────────────────────────────────────

class TestGetAssignmentByIdService:
    def test_returns_existing(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        result = get_assignment_by_id_service(db, a.id)
        assert result.id == a.id

    def test_raises_http404_for_nonexistent(self, db):
        with pytest.raises(HTTPException) as exc:
            get_assignment_by_id_service(db, 9999)
        assert exc.value.status_code == 404


# ── update_assignment_service ──────────────────────────────────────────────────

class TestUpdateAssignmentService:
    def test_updates_title(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, title="Old")
        data = _make_update(c.id, title="New")
        result = update_assignment_service(
            a.id, data, None, [], db, current_user_payload(user.id, "teacher")
        )
        assert result.title == "New"

    def test_raises_for_student_role(self, db):
        user, _ = seed_student(db)
        data = _make_update(1)
        with pytest.raises(ValueError, match="Only teachers"):
            update_assignment_service(
                1, data, None, [], db, current_user_payload(user.id, "student")
            )

    def test_raises_http403_when_no_teacher_profile(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orph@t.com", password="h")
        db.add(user); db.commit()
        data = _make_update(1)
        with pytest.raises(HTTPException) as exc:
            update_assignment_service(
                1, data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 403

    def test_raises_http404_for_nonexistent_assignment(self, db):
        user, _ = seed_teacher(db)
        data = _make_update(1)
        with pytest.raises(HTTPException) as exc:
            update_assignment_service(
                9999, data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 404

    def test_raises_for_wrong_teacher(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        data = _make_update(c.id)
        with pytest.raises(ValueError, match="Not your classroom"):
            update_assignment_service(
                a.id, data, None, [], db, current_user_payload(u2.id, "teacher")
            )

    def test_updates_testcase_url(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        data = _make_update(c.id)
        result = update_assignment_service(
            a.id, data, "https://new.tc", [], db, current_user_payload(user.id, "teacher")
        )
        assert result.testcase_url == "https://new.tc"

    def test_adds_new_attachments(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        data = _make_update(c.id)
        update_assignment_service(
            a.id, data, None, ["https://new.com/f.pdf"],
            db, current_user_payload(user.id, "teacher")
        )
        from app.core.assignment.repository import get_assignment_by_id
        fresh = get_assignment_by_id(db, a.id)
        assert any(att.file_url == "https://new.com/f.pdf" for att in fresh.attachments)

    def test_soft_deletes_attachment(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = seed_attachment(db, a.id, file_url="https://del.com/f.pdf")
        with patch("app.core.assignment.service.delete_file"):
            data = _make_update(c.id, delete_attachment_ids=[att.id])
            update_assignment_service(
                a.id, data, None, [], db, current_user_payload(user.id, "teacher")
            )
        from app.core.assignment.repository import get_attachment_by_id
        assert get_attachment_by_id(db, att.id) is None

    def test_raises_http422_when_start_after_due(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        data = _make_update(c.id, start_date=LATER, due_date=NOW)
        with pytest.raises(HTTPException) as exc:
            update_assignment_service(
                a.id, data, None, [], db, current_user_payload(user.id, "teacher")
            )
        assert exc.value.status_code == 422


# ── delete_assignment_service ──────────────────────────────────────────────────

class TestDeleteAssignmentService:
    def test_raises_for_student_role(self, db):
        user, _ = seed_student(db)
        with pytest.raises(ValueError, match="Only teachers"):
            delete_assignment_service(db, current_user_payload(user.id, "student"), 1)

    def test_raises_http403_when_no_teacher_profile(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orph2@t.com", password="h")
        db.add(user); db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_assignment_service(db, current_user_payload(user.id, "teacher"), 1)
        assert exc.value.status_code == 403

    def test_raises_http404_for_nonexistent(self, db):
        user, _ = seed_teacher(db)
        with pytest.raises(HTTPException) as exc:
            delete_assignment_service(db, current_user_payload(user.id, "teacher"), 9999)
        assert exc.value.status_code == 404

    def test_raises_for_wrong_teacher(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        with pytest.raises(ValueError, match="Not your classroom"):
            delete_assignment_service(
                db, current_user_payload(u2.id, "teacher"), a.id
            )

    def test_bug_nameerror_on_valid_delete(self, db):
        """
        BUG: soft_delete_assignment(db, assignment, tz) — 'tz' undefined.
        Fix: change to soft_delete_assignment(db, assignment) in service.py.
        """
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        with pytest.raises((NameError, TypeError)):
            delete_assignment_service(
                db, current_user_payload(user.id, "teacher"), a.id
            )