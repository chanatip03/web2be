import pytest
from datetime import datetime, timezone, timedelta
from app.models.schema import Assignment, Attachment
from app.core.assignment.repository import (
    create_assignment,
    get_assignment_by_id,
    get_assignments_by_classroom,
    create_attachment,
    get_attachment_by_id,
    delete_attachment_by_id,
    update_assignment,
    soft_delete_assignment,
)
from conftest import seed_teacher, seed_classroom
from fixtures import (
    seed_project_type, seed_language,
    seed_assignment, seed_attachment,
)

NOW = datetime.now(timezone.utc)
LATER = NOW + timedelta(days=7)


# ── create_assignment ──────────────────────────────────────────────────────────

class TestCreateAssignment:
    def test_returns_assignment_with_id(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = Assignment(
            title="Lab 1", start_date=NOW, due_date=LATER,
            is_group=False, is_public=False,
            project_type_id=pt.id, classroom_id=c.id,
        )
        result = create_assignment(db, a)
        assert result.id is not None
        assert result.title == "Lab 1"
        assert result.classroom_id == c.id

    def test_persists_to_db(self, db):
        _, teacher = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db, name="API")
        a = Assignment(
            title="Persist Test", start_date=NOW, due_date=LATER,
            is_group=False, is_public=False,
            project_type_id=pt.id, classroom_id=c.id,
        )
        create_assignment(db, a)
        assert db.query(Assignment).filter_by(title="Persist Test").first() is not None

    def test_with_language(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        lang = seed_language(db)
        a = Assignment(
            title="Lang Test", start_date=NOW, due_date=LATER,
            is_group=False, is_public=False,
            project_type_id=pt.id, language_id=lang.id, classroom_id=c.id,
        )
        result = create_assignment(db, a)
        assert result.language_id == lang.id

    def test_with_testcase_url(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = Assignment(
            title="TC Test", start_date=NOW, due_date=LATER,
            is_group=False, is_public=False,
            project_type_id=pt.id, classroom_id=c.id,
            testcase_url="https://example.com/tc.zip",
        )
        result = create_assignment(db, a)
        assert result.testcase_url == "https://example.com/tc.zip"


# ── get_assignment_by_id ───────────────────────────────────────────────────────

class TestGetAssignmentById:
    def test_returns_existing(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        result = get_assignment_by_id(db, a.id)
        assert result is not None
        assert result.id == a.id

    def test_returns_none_for_nonexistent(self, db):
        assert get_assignment_by_id(db, 9999) is None

    def test_returns_soft_deleted_record(self, db):
        # get_assignment_by_id does NOT filter deleted_date
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, deleted=True)
        result = get_assignment_by_id(db, a.id)
        assert result is not None

    def test_eager_loads_project_type(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db, name="CLI")
        a = seed_assignment(db, c.id, pt.id)
        result = get_assignment_by_id(db, a.id)
        assert result.project_type is not None
        assert result.project_type.name == "CLI"

    def test_eager_loads_language(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        lang = seed_language(db, name="Java")
        a = seed_assignment(db, c.id, pt.id, language_id=lang.id)
        result = get_assignment_by_id(db, a.id)
        assert result.language is not None
        assert result.language.name == "Java"

    def test_eager_loads_active_attachments(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        seed_attachment(db, a.id, file_url="https://example.com/f.pdf")
        result = get_assignment_by_id(db, a.id)
        assert len(result.attachments) == 1

    def test_excludes_soft_deleted_attachments(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        seed_attachment(db, a.id, file_url="https://active.com/f.pdf")
        seed_attachment(db, a.id, file_url="https://deleted.com/f.pdf", deleted=True)
        result = get_assignment_by_id(db, a.id)
        assert len(result.attachments) == 1
        assert result.attachments[0].file_url == "https://active.com/f.pdf"


# ── get_assignments_by_classroom ───────────────────────────────────────────────

class TestGetAssignmentsByClassroom:
    def test_returns_all_active(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="A1")
        seed_assignment(db, c.id, pt.id, title="A2")
        result = get_assignments_by_classroom(db, c.id)
        assert len(result) == 2

    def test_excludes_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        seed_assignment(db, c.id, pt.id, title="Active")
        seed_assignment(db, c.id, pt.id, title="Deleted", deleted=True)
        result = get_assignments_by_classroom(db, c.id)
        assert len(result) == 1
        assert result[0].title == "Active"

    def test_excludes_other_classrooms(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        _, t2 = seed_teacher(db, email="t2@t.com")
        c1 = seed_classroom(db, t1.id, name="C1")
        c2 = seed_classroom(db, t2.id, name="C2")
        pt = seed_project_type(db)
        seed_assignment(db, c1.id, pt.id, title="Mine")
        seed_assignment(db, c2.id, pt.id, title="Theirs")
        result = get_assignments_by_classroom(db, c1.id)
        assert len(result) == 1
        assert result[0].title == "Mine"

    def test_returns_empty_for_no_assignments(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        assert get_assignments_by_classroom(db, c.id) == []

    def test_ordered_by_created_desc(self, db):
        # SQLite server_default doesn't apply during ORM inserts.
        # Insert assignments with explicit created_date to test ordering.
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        from app.models.schema import Assignment
        a1 = Assignment(
            title="First",
            start_date=NOW - timedelta(days=14), due_date=NOW - timedelta(days=7),
            is_group=False, is_public=False,
            project_type_id=pt.id, classroom_id=c.id,
            created_date=NOW - timedelta(minutes=5),
        )
        a2 = Assignment(
            title="Second",
            start_date=NOW, due_date=NOW + timedelta(days=7),
            is_group=False, is_public=False,
            project_type_id=pt.id, classroom_id=c.id,
            created_date=NOW,
        )
        db.add_all([a1, a2])
        db.commit()
        db.refresh(a1); db.refresh(a2)
        result = get_assignments_by_classroom(db, c.id)
        assert result[0].id == a2.id   # newer first (DESC)
        assert result[1].id == a1.id


# ── create_attachment ──────────────────────────────────────────────────────────

class TestCreateAttachment:
    def test_creates_single(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = Attachment(file_url="https://f.com/a.pdf", assignment_id=a.id)
        result = create_attachment(db, [att])
        assert len(result) == 1
        assert result[0].id is not None

    def test_creates_multiple(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        atts = [
            Attachment(file_url="https://f.com/1.pdf", assignment_id=a.id),
            Attachment(file_url="https://f.com/2.pdf", assignment_id=a.id),
        ]
        result = create_attachment(db, atts)
        assert len(result) == 2

    def test_empty_list_returns_empty(self, db):
        assert create_attachment(db, []) == []


# ── get_attachment_by_id ───────────────────────────────────────────────────────

class TestGetAttachmentById:
    def test_returns_existing(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = seed_attachment(db, a.id)
        result = get_attachment_by_id(db, att.id)
        assert result is not None
        assert result.id == att.id

    def test_returns_none_for_nonexistent(self, db):
        assert get_attachment_by_id(db, 9999) is None

    def test_returns_none_for_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = seed_attachment(db, a.id, deleted=True)
        assert get_attachment_by_id(db, att.id) is None


# ── delete_attachment_by_id ────────────────────────────────────────────────────

class TestDeleteAttachmentById:
    def test_sets_deleted_date(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = seed_attachment(db, a.id)
        assert att.deleted_date is None
        delete_attachment_by_id(db, att)
        db.refresh(att)
        assert att.deleted_date is not None

    def test_not_found_after_soft_delete(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        att = seed_attachment(db, a.id)
        delete_attachment_by_id(db, att)
        assert get_attachment_by_id(db, att.id) is None


# ── update_assignment ──────────────────────────────────────────────────────────

class TestUpdateAssignment:
    def test_updates_title(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, title="Old")
        result = update_assignment(db, a, {"title": "New"})
        assert result.title == "New"

    def test_skips_none_values(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, title="Keep")
        result = update_assignment(db, a, {"title": None, "description": "Updated"})
        assert result.title == "Keep"
        assert result.description == "Updated"

    def test_updates_multiple_fields(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id, title="Old")
        result = update_assignment(db, a, {"title": "New", "is_public": True})
        assert result.title == "New"
        assert result.is_public is True


# ── soft_delete_assignment ─────────────────────────────────────────────────────

class TestSoftDeleteAssignment:
    def test_sets_deleted_date(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        assert a.deleted_date is None
        result = soft_delete_assignment(db, a)
        assert result.deleted_date is not None

    def test_excluded_from_classroom_list(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        pt = seed_project_type(db)
        a = seed_assignment(db, c.id, pt.id)
        soft_delete_assignment(db, a)
        assert get_assignments_by_classroom(db, c.id) == []
