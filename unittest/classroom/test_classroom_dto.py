import pytest
from pydantic import ValidationError
from app.core.classroom.dto import (
    CreateClassroomRequest,
    ClassroomUpdateDTO,
)


class TestCreateClassroomRequest:
    def test_all_fields(self):
        data = CreateClassroomRequest(
            name="Python 101",
            semester="1/2025",
            description="Intro course",
            learningoutcomes="Understand basic Python",
        )
        assert data.name == "Python 101"
        assert data.semester == "1/2025"
        assert data.description == "Intro course"
        assert data.learningoutcomes == "Understand basic Python"

    def test_required_only(self):
        data = CreateClassroomRequest(name="Math", semester="2/2025")
        assert data.description is None
        assert data.learningoutcomes is None

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            CreateClassroomRequest(semester="1/2025")

    def test_missing_semester_raises(self):
        with pytest.raises(ValidationError):
            CreateClassroomRequest(name="Math")

    def test_empty_raises(self):
        with pytest.raises(ValidationError):
            CreateClassroomRequest()


class TestClassroomUpdateDTO:
    def test_all_none(self):
        data = ClassroomUpdateDTO(name=None, semester=None, description=None)
        assert data.name is None

    def test_partial_fields(self):
        data = ClassroomUpdateDTO(name="New", semester="2/2025", description=None)
        assert data.name == "New"
        assert data.semester == "2/2025"

    def test_learningoutcomes_defaults_none(self):
        data = ClassroomUpdateDTO(name="X", semester="1/2025", description="desc")
        assert data.learningoutcomes is None

    def test_learningoutcomes_set(self):
        data = ClassroomUpdateDTO(
            name="X", semester="1/2025",
            description=None, learningoutcomes="Solve equations",
        )
        assert data.learningoutcomes == "Solve equations"