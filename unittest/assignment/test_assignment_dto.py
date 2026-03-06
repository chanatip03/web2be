import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError
from app.core.assignment.dto import (
    CreateAssignmentRequest,
    UpdateAssignmentRequest,
    AssignmentResponse,
)

NOW = datetime.now(timezone.utc)
LATER = NOW + timedelta(days=7)


# ── CreateAssignmentRequest ────────────────────────────────────────────────────

class TestCreateAssignmentRequest:
    def test_all_required_fields(self):
        data = CreateAssignmentRequest(
            title="Lab 1", description=None,
            start_date=NOW, due_date=LATER,
            is_group=False, project_type_id=1,
            language_id=None, classroom_id=1,
        )
        assert data.title == "Lab 1"
        assert data.classroom_id == 1
        assert data.language_id is None

    def test_with_all_optional_fields(self):
        data = CreateAssignmentRequest(
            title="Lab 2", description="Do something",
            start_date=NOW, due_date=LATER,
            is_group=True, project_type_id=2,
            language_id=3, classroom_id=5,
        )
        assert data.description == "Do something"
        assert data.language_id == 3
        assert data.is_group is True

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            CreateAssignmentRequest(
                start_date=NOW, due_date=LATER,
                is_group=False, project_type_id=1, classroom_id=1,
            )

    def test_missing_start_date_raises(self):
        with pytest.raises(ValidationError):
            CreateAssignmentRequest(
                title="X", due_date=LATER,
                is_group=False, project_type_id=1, classroom_id=1,
            )

    def test_missing_due_date_raises(self):
        with pytest.raises(ValidationError):
            CreateAssignmentRequest(
                title="X", start_date=NOW,
                is_group=False, project_type_id=1, classroom_id=1,
            )

    def test_missing_classroom_id_raises(self):
        with pytest.raises(ValidationError):
            CreateAssignmentRequest(
                title="X", start_date=NOW, due_date=LATER,
                is_group=False, project_type_id=1,
            )

    def test_missing_project_type_id_raises(self):
        with pytest.raises(ValidationError):
            CreateAssignmentRequest(
                title="X", start_date=NOW, due_date=LATER,
                is_group=False, classroom_id=1,
            )

    def test_naive_datetime_gets_timezone(self):
        naive = datetime(2025, 6, 1, 9, 0, 0)   # no tzinfo
        data = CreateAssignmentRequest(
            title="X", start_date=naive, due_date=LATER,
            is_group=False, project_type_id=1, classroom_id=1,
        )
        assert data.start_date.tzinfo is not None

    def test_aware_datetime_unchanged(self):
        data = CreateAssignmentRequest(
            title="X", start_date=NOW, due_date=LATER,
            is_group=False, project_type_id=1, classroom_id=1,
        )
        assert data.start_date == NOW


# ── UpdateAssignmentRequest ────────────────────────────────────────────────────

class TestUpdateAssignmentRequest:
    def test_only_classroom_id_required(self):
        data = UpdateAssignmentRequest(classroom_id=1)
        assert data.classroom_id == 1
        assert data.title is None
        assert data.delete_attachment_ids is None

    def test_full_update_payload(self):
        data = UpdateAssignmentRequest(
            title="New Title", description="Updated",
            start_date=NOW, due_date=LATER,
            is_group=True, is_public=True,
            project_type_id=2, language_id=1,
            classroom_id=3,
            delete_attachment_ids=[10, 20],
            delete_testcase_url="https://old.url",
        )
        assert data.title == "New Title"
        assert data.delete_attachment_ids == [10, 20]
        assert data.delete_testcase_url == "https://old.url"

    def test_missing_classroom_id_raises(self):
        with pytest.raises(ValidationError):
            UpdateAssignmentRequest(title="X")

    def test_parse_ids_from_comma_string(self):
        # parse_ids validator converts "1,2,3" → [1, 2, 3]
        data = UpdateAssignmentRequest(classroom_id=1, delete_attachment_ids="1,2,3")
        assert data.delete_attachment_ids == [1, 2, 3]

    def test_parse_ids_single_value(self):
        data = UpdateAssignmentRequest(classroom_id=1, delete_attachment_ids="7")
        assert data.delete_attachment_ids == [7]

    def test_parse_ids_none_stays_none(self):
        data = UpdateAssignmentRequest(classroom_id=1, delete_attachment_ids=None)
        assert data.delete_attachment_ids is None

    def test_parse_ids_list_passthrough(self):
        data = UpdateAssignmentRequest(classroom_id=1, delete_attachment_ids=[5, 6])
        assert data.delete_attachment_ids == [5, 6]


# ── AssignmentResponse ─────────────────────────────────────────────────────────

class TestAssignmentResponse:
    def _base(self, **kwargs):
        defaults = dict(
            id=1, title="Lab 1", description=None,
            start_date=NOW, due_date=LATER,
            is_group=False, is_public=False,
            project_type={"id": 1, "name": "Web"},
            language=None, testcase_url=None, attachments=[],
        )
        defaults.update(kwargs)
        return AssignmentResponse.model_validate(defaults)

    def test_minimal_valid_response(self):
        resp = self._base()
        assert resp.id == 1
        assert resp.title == "Lab 1"
        assert resp.attachments == []
        assert resp.language is None

    def test_project_type_alias(self):
        resp = self._base()
        # field name is projectType, source alias is project_type
        assert resp.projectType.id == 1
        assert resp.projectType.name == "Web"

    def test_testcase_url_alias(self):
        resp = self._base(testcase_url="https://tc.url")
        assert resp.testcaseUrl == "https://tc.url"

    def test_with_language(self):
        resp = self._base(language={"id": 2, "name": "Python"})
        assert resp.language is not None
        assert resp.language.name == "Python"

    def test_with_attachments(self):
        resp = self._base(attachments=[
            {"id": 1, "file_url": "https://a.com/f.pdf"},
            {"id": 2, "file_url": "https://a.com/g.pdf"},
        ])
        assert len(resp.attachments) == 2
        # Attachment.fileUrl uses alias file_url
        assert resp.attachments[0].fileUrl == "https://a.com/f.pdf"

    def test_is_public_default(self):
        resp = self._base(is_public=False)
        assert resp.is_public is False