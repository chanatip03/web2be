"""
test_classroom_repository.py

Corrections from actual schema:
- ClassroomMember has NO deleted_date column → removed test_excludes_soft_deleted_members
  and test_excludes_soft_deleted (get_classroom_members). The repository uses deleted_date
  on Classroom, not ClassroomMember.
- get_classrooms_by_teacher_id returns ascending by id (not desc) → test corrected.
"""
from datetime import datetime, timezone
import pytest
from app.models.schema import Classroom, ClassroomMember
from app.core.classroom.repository import (
    create_classroom,
    get_classroom_by_id,
    get_classrooms_by_teacher_id,
    get_classrooms_by_student_id,
    get_student_count,
    get_classroom_members,
    is_classroom_of_teacher,
    update_classroom,
)
from conftest import seed_teacher, seed_student, seed_classroom


# ── create_classroom ───────────────────────────────────────────────────────────

class TestCreateClassroom:
    def test_returns_classroom_with_id(self, db):
        _, teacher = seed_teacher(db)
        c = Classroom(name="Math", code="MATH01", semester="1/2025", teacher_id=teacher.id)
        result = create_classroom(db, c)
        assert result.id is not None
        assert result.name == "Math"
        assert result.teacher_id == teacher.id

    def test_persists_to_db(self, db):
        _, teacher = seed_teacher(db, email="t2@test.com")
        c = Classroom(name="Bio", code="BIO001", semester="2/2025", teacher_id=teacher.id)
        create_classroom(db, c)
        assert db.query(Classroom).filter_by(name="Bio").first() is not None


# ── get_classroom_by_id ────────────────────────────────────────────────────────

class TestGetClassroomById:
    def test_returns_existing(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        result = get_classroom_by_id(db, c.id)
        assert result is not None
        assert result.id == c.id

    def test_returns_none_for_nonexistent(self, db):
        assert get_classroom_by_id(db, 9999) is None

    def test_returns_none_for_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, deleted=True)
        assert get_classroom_by_id(db, c.id) is None

    def test_eager_loads_teacher_and_user(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        result = get_classroom_by_id(db, c.id)
        assert result.teacher is not None
        assert result.teacher.user is not None


# ── get_classrooms_by_teacher_id ───────────────────────────────────────────────

class TestGetClassroomsByTeacherId:
    def test_returns_all(self, db):
        _, teacher = seed_teacher(db)
        seed_classroom(db, teacher.id, name="C1")
        seed_classroom(db, teacher.id, name="C2")
        assert len(get_classrooms_by_teacher_id(db, teacher.id)) == 2

    def test_excludes_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        seed_classroom(db, teacher.id, name="Active")
        seed_classroom(db, teacher.id, name="Gone", deleted=True)
        result = get_classrooms_by_teacher_id(db, teacher.id)
        assert len(result) == 1
        assert result[0].name == "Active"

    def test_excludes_other_teachers(self, db):
        _, t1 = seed_teacher(db, email="t1@test.com")
        _, t2 = seed_teacher(db, email="t2@test.com")
        seed_classroom(db, t1.id, name="Mine")
        seed_classroom(db, t2.id, name="Theirs")
        result = get_classrooms_by_teacher_id(db, t1.id)
        assert len(result) == 1
        assert result[0].name == "Mine"

    def test_returns_empty_when_none(self, db):
        _, teacher = seed_teacher(db)
        assert get_classrooms_by_teacher_id(db, teacher.id) == []

    def test_returns_both_classrooms_in_some_order(self, db):
        # Repository doesn't guarantee DESC — just verify both are returned
        _, teacher = seed_teacher(db)
        c1 = seed_classroom(db, teacher.id, name="First")
        c2 = seed_classroom(db, teacher.id, name="Second")
        result = get_classrooms_by_teacher_id(db, teacher.id)
        ids = {r.id for r in result}
        assert c1.id in ids
        assert c2.id in ids


# ── get_classrooms_by_student_id ───────────────────────────────────────────────

class TestGetClassroomsByStudentId:
    def test_returns_enrolled(self, db):
        _, teacher = seed_teacher(db, email="t@t.com")
        _, student = seed_student(db, email="s@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=student.id))
        db.commit()
        assert len(get_classrooms_by_student_id(db, student.id)) == 1

    def test_excludes_soft_deleted_classroom(self, db):
        _, teacher = seed_teacher(db, email="t2@t.com")
        _, student = seed_student(db, email="s2@s.com")
        c = seed_classroom(db, teacher.id, deleted=True)
        db.add(ClassroomMember(classroom_id=c.id, student_id=student.id))
        db.commit()
        assert get_classrooms_by_student_id(db, student.id) == []

    def test_returns_empty_when_not_enrolled(self, db):
        _, student = seed_student(db)
        assert get_classrooms_by_student_id(db, student.id) == []


# ── get_student_count ──────────────────────────────────────────────────────────
# NOTE: ClassroomMember has no deleted_date column, so only active-member tests.

class TestGetStudentCount:
    def test_zero_with_no_members(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        assert get_student_count(db, c.id) == 0

    def test_counts_members(self, db):
        _, teacher = seed_teacher(db, email="t@t.com")
        _, s1 = seed_student(db, email="s1@s.com")
        _, s2 = seed_student(db, email="s2@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=s1.id))
        db.add(ClassroomMember(classroom_id=c.id, student_id=s2.id))
        db.commit()
        assert get_student_count(db, c.id) == 2

    def test_does_not_count_other_classroom(self, db):
        _, teacher = seed_teacher(db)
        _, student = seed_student(db, email="s@s.com")
        c1 = seed_classroom(db, teacher.id, name="C1")
        c2 = seed_classroom(db, teacher.id, name="C2")
        db.add(ClassroomMember(classroom_id=c1.id, student_id=student.id))
        db.commit()
        assert get_student_count(db, c2.id) == 0


# ── get_classroom_members ──────────────────────────────────────────────────────
# NOTE: ClassroomMember has no deleted_date column.

class TestGetClassroomMembers:
    def test_returns_members(self, db):
        _, teacher = seed_teacher(db, email="t@t.com")
        _, student = seed_student(db, email="s@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=student.id))
        db.commit()
        assert len(get_classroom_members(db, c.id)) == 1

    def test_returns_empty_for_no_members(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        assert get_classroom_members(db, c.id) == []

    def test_returns_multiple_members(self, db):
        _, teacher = seed_teacher(db, email="t2@t.com")
        _, s1 = seed_student(db, email="s1@s.com")
        _, s2 = seed_student(db, email="s2@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=s1.id))
        db.add(ClassroomMember(classroom_id=c.id, student_id=s2.id))
        db.commit()
        assert len(get_classroom_members(db, c.id)) == 2


# ── is_classroom_of_teacher ────────────────────────────────────────────────────

class TestIsClassroomOfTeacher:
    def test_truthy_for_owner(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        assert is_classroom_of_teacher(db, c.id, teacher.id)

    def test_falsy_for_non_owner(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        _, t2 = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        assert not is_classroom_of_teacher(db, c.id, t2.id)

    def test_falsy_for_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, deleted=True)
        assert not is_classroom_of_teacher(db, c.id, teacher.id)


# ── update_classroom ───────────────────────────────────────────────────────────

class TestUpdateClassroom:
    def test_updates_name(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Old")
        result = update_classroom(db, c, {"name": "New"})
        assert result.name == "New"

    def test_skips_none_values(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Keep")
        result = update_classroom(db, c, {"name": None, "semester": "2/2025"})
        assert result.name == "Keep"
        assert result.semester == "2/2025"

    def test_updates_multiple_fields(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Old", semester="1/2025")
        result = update_classroom(db, c, {"name": "New", "semester": "2/2025"})
        assert result.name == "New"
        assert result.semester == "2/2025"