"""
Tests: Controller / Route Layer
ครอบคลุม: classroom endpoints, admin endpoint, auth endpoints
"""
import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────
# Classroom Controller
# ─────────────────────────────────────────────
class TestClassroomController:
    def test_create_classroom_success(self, client, db, make_teacher):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher

        # สร้าง teacher id=1 (user_id_mock ใน controller)
        user = User(id=1, first_name="T", last_name="S", email="t@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.flush()
        teacher = Teacher(user_id=1, certificate_url="https://cert")
        db.add(teacher)
        db.commit()

        resp = client.post("/api/classroom/", json={
            "name": "Math 101",
            "semester": "1/2025",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Math 101"
        assert data["semester"] == "1/2025"
        assert len(data["code"]) == 8
        assert "id" in data

    def test_create_classroom_not_teacher_returns_403(self, client, db, make_user):
        from app.utils.generate_token import hash_password
        from app.models.schema import User

        # user_id=1 แต่ไม่มี teacher profile
        user = User(id=1, first_name="S", last_name="T", email="s@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.commit()

        resp = client.post("/api/classroom/", json={
            "name": "Math 101",
            "semester": "1/2025",
        })
        assert resp.status_code == 403

    def test_create_classroom_missing_field_returns_422(self, client):
        resp = client.post("/api/classroom/", json={"name": "Math 101"})
        assert resp.status_code == 422

    def test_get_classrooms_empty(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher

        user = User(id=1, first_name="T", last_name="S", email="t@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.flush()
        teacher = Teacher(user_id=1)
        db.add(teacher)
        db.commit()

        resp = client.get("/api/classroom/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["classrooms"] == []
        assert data["total"] == 0

    def test_get_classrooms_returns_list(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher
        from app.core.classroom.repository import create_classroom

        user = User(id=1, first_name="T", last_name="S", email="t@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.flush()
        teacher = Teacher(user_id=1)
        db.add(teacher)
        db.commit()

        create_classroom(db, "Algebra", "1/2025", teacher.id)

        resp = client.get("/api/classroom/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["classrooms"][0]["name"] == "Algebra"

    def test_get_classroom_by_id_success(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher
        from app.core.classroom.repository import create_classroom

        user = User(id=1, first_name="T", last_name="S", email="t@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.flush()
        teacher = Teacher(user_id=1)
        db.add(teacher)
        db.commit()

        classroom = create_classroom(db, "Chemistry", "1/2025", teacher.id)

        resp = client.get(f"/api/classroom/{classroom.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Chemistry"

    def test_get_classroom_by_id_not_found(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher

        user = User(id=1, first_name="T", last_name="S", email="t@t.com",
                    password=hash_password("pass"), academy="Uni")
        db.add(user)
        db.flush()
        teacher = Teacher(user_id=1)
        db.add(teacher)
        db.commit()

        resp = client.get("/api/classroom/99999")
        assert resp.status_code == 404

    def test_get_classroom_wrong_teacher_returns_404(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import User, Teacher
        from app.core.classroom.repository import create_classroom

        # teacher A (user_id=2) สร้าง classroom
        user_a = User(id=2, first_name="A", last_name="T", email="a@t.com",
                      password=hash_password("pass"), academy="Uni")
        db.add(user_a)
        db.flush()
        teacher_a = Teacher(user_id=2)
        db.add(teacher_a)

        # user_id=1 (mock) ไม่มี teacher profile
        user_mock = User(id=1, first_name="M", last_name="T", email="m@t.com",
                         password=hash_password("pass"), academy="Uni")
        db.add(user_mock)
        db.commit()

        classroom = create_classroom(db, "Bio", "1/2025", teacher_a.id)

        resp = client.get(f"/api/classroom/{classroom.id}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────
# Admin Controller
# ─────────────────────────────────────────────
class TestAdminController:
    def test_create_admin_success(self, client):
        resp = client.post("/api/admin/", json={
            "email": "newadmin@test.com",
            "password": "securepass"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "newadmin@test.com"
        assert "id" in data

    def test_create_admin_duplicate_returns_400(self, client):
        client.post("/api/admin/", json={"email": "dup@test.com", "password": "pass"})
        resp = client.post("/api/admin/", json={"email": "dup@test.com", "password": "pass2"})
        assert resp.status_code == 400

    def test_create_admin_invalid_email_returns_422(self, client):
        resp = client.post("/api/admin/", json={"email": "not-email", "password": "pass"})
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# Auth Controller
# ─────────────────────────────────────────────
class TestAuthController:
    def test_login_admin_success(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import Admin
        admin = Admin(email="admin@test.com", password=hash_password("adminpass"))
        db.add(admin)
        db.commit()

        resp = client.post("/api/auth/login-admin", json={
            "email": "admin@test.com",
            "password": "adminpass"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_admin_wrong_password_returns_401(self, client, db):
        from app.utils.generate_token import hash_password
        from app.models.schema import Admin
        admin = Admin(email="admin2@test.com", password=hash_password("correct"))
        db.add(admin)
        db.commit()

        resp = client.post("/api/auth/login-admin", json={
            "email": "admin2@test.com",
            "password": "wrong"
        })
        assert resp.status_code == 401

    def test_login_admin_not_found_returns_401(self, client):
        resp = client.post("/api/auth/login-admin", json={
            "email": "nobody@test.com",
            "password": "pass"
        })
        assert resp.status_code == 401

    def test_login_user_success(self, client, db):
        from app.core.student.service import create_student
        create_student(db, "Bob", "Lee", "bob@test.com", "mypass", "MIT", "S001")

        resp = client.post("/api/auth/login", json={
            "email": "bob@test.com",
            "password": "mypass"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_user_wrong_password_returns_401(self, client, db):
        from app.core.student.service import create_student
        create_student(db, "Ann", "Smith", "ann@test.com", "correct", "MIT", "S002")

        resp = client.post("/api/auth/login", json={
            "email": "ann@test.com",
            "password": "wrong"
        })
        assert resp.status_code == 401

    def test_login_user_not_found_returns_401(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "ghost@test.com",
            "password": "pass"
        })
        assert resp.status_code == 401

    def test_check_token_no_cookie_returns_401(self, client):
        resp = client.post("/api/auth/check-user-token")
        assert resp.status_code == 401

    def test_check_token_valid(self, client, db):
        from app.core.student.service import create_student
        from app.utils.generate_token import create_access_token
        create_student(db, "Eve", "K", "eve@test.com", "pass", "Caltech", "S003")

        token = create_access_token({"userId": "999", "role": "student"})
        client.cookies.set("access_token", token)
        resp = client.post("/api/auth/check-user-token")
        assert resp.status_code == 200
        client.cookies.clear()