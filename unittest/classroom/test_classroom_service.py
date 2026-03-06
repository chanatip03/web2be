import pytest
from app.models.schema import Classroom, ClassroomMember
from app.core.classroom.dto import CreateClassroomRequest, ClassroomUpdateDTO
from app.core.classroom.service import (
    create_new_classroom,
    get_classrooms_service,
    get_classroom_by_id_service,
    update_classroom_service,
    generate_classroom_code,
)
from conftest import seed_teacher, seed_student, seed_classroom, current_user_payload

# ── generate_classroom_code ────────────────────────────────────────────────────

class TestGenerateClassroomCode:
    def test_length_is_6(self):
        assert len(generate_classroom_code()) == 6

    def test_uppercase_alphanumeric(self):
        code = generate_classroom_code()
        assert code.isalnum()
        assert code == code.upper()

    def test_generates_unique_values(self):
        codes = {generate_classroom_code() for _ in range(100)}
        assert len(codes) > 1


# ── create_new_classroom ───────────────────────────────────────────────────────

class TestCreateNewClassroom:
    def test_creates_for_teacher(self, db):
        user, teacher = seed_teacher(db)
        data = CreateClassroomRequest(name="CS101", semester="1/2025")
        result = create_new_classroom(data, db, current_user_payload(user.id, "teacher"))
        assert result.id is not None
        assert result.name == "CS101"
        assert result.teacher_id == teacher.id
        assert len(result.code) == 6

    def test_creates_with_description_and_outcomes(self, db):
        user, _ = seed_teacher(db)
        data = CreateClassroomRequest(
            name="Math", semester="2/2025",
            description="Advanced", learningoutcomes="Solve equations",
        )
        result = create_new_classroom(data, db, current_user_payload(user.id, "teacher"))
        assert result.description == "Advanced"
        assert result.learningoutcomes == "Solve equations"

    def test_raises_for_non_teacher_role(self, db):
        user, _ = seed_student(db)
        data = CreateClassroomRequest(name="X", semester="1/2025")
        with pytest.raises(ValueError, match="Only teachers can create classrooms"):
            create_new_classroom(data, db, current_user_payload(user.id, "student"))

    def test_raises_when_no_teacher_profile(self, db):
        # User exists in JWT but Teacher record is missing
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan@test.com", password="h")
        db.add(user)
        db.commit()
        data = CreateClassroomRequest(name="X", semester="1/2025")
        with pytest.raises(ValueError, match="Teacher profile not found"):
            create_new_classroom(data, db, current_user_payload(user.id, "teacher"))


# ── get_classrooms_service ─────────────────────────────────────────────────────

class TestGetClassroomsService:
    def test_teacher_gets_own_classrooms(self, db):
        user, teacher = seed_teacher(db)
        seed_classroom(db, teacher.id)
        result = get_classrooms_service(db, current_user_payload(user.id, "teacher"))
        assert len(result) == 1

    def test_student_gets_enrolled_classrooms(self, db):
        _, teacher = seed_teacher(db, email="t@t.com")
        s_user, student = seed_student(db, email="s@s.com")
        c = seed_classroom(db, teacher.id)
        db.add(ClassroomMember(classroom_id=c.id, student_id=student.id))
        db.commit()
        result = get_classrooms_service(db, current_user_payload(s_user.id, "student"))
        assert len(result) == 1

    def test_teacher_no_classrooms_returns_empty(self, db):
        user, _ = seed_teacher(db)
        assert get_classrooms_service(db, current_user_payload(user.id, "teacher")) == []

    def test_unknown_role_returns_empty(self, db):
        assert get_classrooms_service(db, {"id": 99, "role": "admin"}) == []

    def test_teacher_without_profile_returns_empty(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan@test.com", password="h")
        db.add(user)
        db.commit()
        assert get_classrooms_service(db, current_user_payload(user.id, "teacher")) == []

    def test_student_without_profile_returns_empty(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan2@test.com", password="h")
        db.add(user)
        db.commit()
        assert get_classrooms_service(db, current_user_payload(user.id, "student")) == []


# ── get_classroom_by_id_service ────────────────────────────────────────────────

class TestGetClassroomByIdService:
    def test_returns_existing(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        result = get_classroom_by_id_service(db, c.id)
        assert result is not None
        assert result.id == c.id

    def test_returns_none_for_nonexistent(self, db):
        assert get_classroom_by_id_service(db, 9999) is None

    def test_returns_none_for_soft_deleted(self, db):
        _, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, deleted=True)
        assert get_classroom_by_id_service(db, c.id) is None


# ── update_classroom_service ───────────────────────────────────────────────────

class TestUpdateClassroomService:
    def test_updates_successfully(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id, name="Old")
        payload = ClassroomUpdateDTO(name="New Name", semester="2/2025",
                                      description=None, learningoutcomes=None)
        result = update_classroom_service(db, c.id, current_user_payload(user.id, "teacher"), payload)
        assert result.name == "New Name"
        assert result.semester == "2/2025"

    def test_raises_for_non_teacher_role(self, db):
        s_user, _ = seed_student(db)
        payload = ClassroomUpdateDTO(name="X", semester="1/2025", description=None)
        with pytest.raises(ValueError, match="Only teachers can update classrooms"):
            update_classroom_service(db, 1, current_user_payload(s_user.id, "student"), payload)

    def test_raises_when_no_teacher_profile(self, db):
        from app.models.schema import User
        user = User(first_name="O", last_name="R", email="orphan@test.com", password="h")
        db.add(user)
        db.commit()
        payload = ClassroomUpdateDTO(name="X", semester="1/2025", description=None)
        with pytest.raises(ValueError, match="Teacher profile not found"):
            update_classroom_service(db, 1, current_user_payload(user.id, "teacher"), payload)

    def test_raises_for_wrong_teacher(self, db):
        _, t1 = seed_teacher(db, email="t1@t.com")
        u2, _ = seed_teacher(db, email="t2@t.com")
        c = seed_classroom(db, t1.id)
        payload = ClassroomUpdateDTO(name="Hack", semester="1/2025", description=None)
        with pytest.raises(ValueError, match="Classroom not found"):
            update_classroom_service(db, c.id, current_user_payload(u2.id, "teacher"), payload)

    def test_updates_learningoutcomes(self, db):
        user, teacher = seed_teacher(db)
        c = seed_classroom(db, teacher.id)
        payload = ClassroomUpdateDTO(name=c.name, semester=c.semester,
                                      description=None, learningoutcomes="Understand cells")
        result = update_classroom_service(db, c.id, current_user_payload(user.id, "teacher"), payload)
        assert result.learningoutcomes == "Understand cells"