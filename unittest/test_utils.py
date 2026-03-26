"""
Tests: Utility functions
ครอบคลุม: generate_token, otp helpers, security_scan normalizer
"""
import pytest
from unittest.mock import patch, MagicMock
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("HASH_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")


# ─────────────────────────────────────────────
# Token utilities
# ─────────────────────────────────────────────
class TestGenerateToken:
    def test_hash_password_returns_hash(self):
        from app.utils.generate_token import hash_password
        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert len(hashed) > 20

    def test_hash_password_different_each_time(self):
        from app.utils.generate_token import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt salt

    def test_verify_password_correct(self):
        from app.utils.generate_token import hash_password, verify_password
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_verify_password_wrong(self):
        from app.utils.generate_token import hash_password, verify_password
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False

    def test_create_access_token_returns_string(self):
        from app.utils.generate_token import create_access_token
        token = create_access_token({"userId": "1", "role": "student"})
        assert isinstance(token, str)
        assert len(token) > 10

    def test_decode_token_valid(self):
        from app.utils.generate_token import create_access_token, decode_token
        token = create_access_token({"userId": "42", "role": "teacher"})
        payload = decode_token(token)
        assert payload["userId"] == "42"
        assert payload["role"] == "teacher"

    def test_decode_token_invalid_raises(self):
        from app.utils.generate_token import decode_token
        from jose import JWTError
        with pytest.raises(Exception):
            decode_token("invalid.token.here")

    def test_create_token_includes_exp(self):
        from app.utils.generate_token import create_access_token, decode_token
        token = create_access_token({"userId": "1", "role": "admin"})
        payload = decode_token(token)
        assert "exp" in payload

    def test_create_token_sub_maps_to_userId(self):
        """ถ้าส่ง sub แทน userId ควร map ให้อัตโนมัติ"""
        from app.utils.generate_token import create_access_token, decode_token
        token = create_access_token({"sub": "99", "type": "admin"})
        payload = decode_token(token)
        assert payload.get("userId") == "99"

    def test_create_token_type_maps_to_role(self):
        """ถ้าส่ง type แทน role ควร map ให้อัตโนมัติ"""
        from app.utils.generate_token import create_access_token, decode_token
        token = create_access_token({"sub": "5", "type": "admin"})
        payload = decode_token(token)
        assert payload.get("role") == "admin"


# ─────────────────────────────────────────────
# OTP utilities
# ─────────────────────────────────────────────
class TestOTPUtils:
    def test_generate_otp_length(self):
        from app.utils.otp import generate_otp
        otp = generate_otp()
        assert len(otp) == 6

    def test_generate_otp_is_numeric(self):
        from app.utils.otp import generate_otp
        for _ in range(10):
            otp = generate_otp()
            assert otp.isdigit()

    def test_generate_otp_range(self):
        from app.utils.otp import generate_otp
        for _ in range(20):
            otp = int(generate_otp())
            assert 100000 <= otp <= 999999

    def test_hash_otp_returns_hex(self):
        from app.utils.otp import hash_otp
        hashed = hash_otp("123456")
        assert len(hashed) == 64  # sha256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in hashed)

    def test_hash_otp_same_input_same_output(self):
        from app.utils.otp import hash_otp
        assert hash_otp("999999") == hash_otp("999999")

    def test_hash_otp_different_input_different_output(self):
        from app.utils.otp import hash_otp
        assert hash_otp("111111") != hash_otp("222222")

    def test_save_and_get_otp_memory(self):
        from app.utils.otp import save_otp_memory, get_otp_memory, delete_otp_memory
        save_otp_memory("test@test.com", "hashed_otp", {"role": "student", "data": {}})
        record = get_otp_memory("test@test.com")

        assert record is not None
        assert record["otp"] == "hashed_otp"
        assert "expires" in record
        delete_otp_memory("test@test.com")

    def test_get_otp_memory_not_found(self):
        from app.utils.otp import get_otp_memory
        record = get_otp_memory("nobody@test.com")
        assert record is None

    def test_delete_otp_memory(self):
        from app.utils.otp import save_otp_memory, get_otp_memory, delete_otp_memory
        save_otp_memory("del@test.com", "hash", {})
        delete_otp_memory("del@test.com")
        assert get_otp_memory("del@test.com") is None

    def test_delete_otp_memory_nonexistent_no_error(self):
        from app.utils.otp import delete_otp_memory
        delete_otp_memory("ghost@test.com")  # ไม่ควร raise


# ─────────────────────────────────────────────
# Security Scan Normalizer
# ─────────────────────────────────────────────
class TestNormalizer:
    def test_empty_raw_returns_zero_issues(self):
        from app.core.security_scan.normalizer import normalize_code_result
        result = normalize_code_result({"runs": []})
        assert result["issues_found"] == 0
        assert result["issues"] == []

    def test_empty_runs_returns_empty(self):
        from app.core.security_scan.normalizer import normalize_code_result
        result = normalize_code_result({})
        assert result["issues_found"] == 0

    def test_normalizes_single_issue(self):
        from app.core.security_scan.normalizer import normalize_code_result
        raw = {
            "runs": [{
                "results": [{
                    "ruleId": "CWE-89",
                    "level": "error",
                    "message": {"text": "SQL Injection"},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": "app/main.py"},
                            "region": {"startLine": 10, "endLine": 12}
                        }
                    }]
                }]
            }]
        }
        result = normalize_code_result(raw)
        assert result["issues_found"] == 1
        issue = result["issues"][0]
        assert issue["rule"] == "CWE-89"
        assert issue["severity"] == "error"
        assert issue["message"] == "SQL Injection"
        assert issue["locations"][0]["file"] == "app/main.py"
        assert issue["locations"][0]["startLine"] == 10

    def test_normalizes_multiple_issues(self):
        from app.core.security_scan.normalizer import normalize_code_result
        raw = {
            "runs": [{
                "results": [
                    {"ruleId": "A", "level": "warning", "message": {"text": "Warn"}, "locations": []},
                    {"ruleId": "B", "level": "error", "message": {"text": "Error"}, "locations": []},
                ]
            }]
        }
        result = normalize_code_result(raw)
        assert result["issues_found"] == 2

    def test_includes_languages_from_meta(self):
        from app.core.security_scan.normalizer import normalize_code_result
        raw = {
            "_meta": {"languages": ["python", "javascript"]},
            "runs": []
        }
        result = normalize_code_result(raw)
        assert result["languages"] == ["python", "javascript"]

    def test_type_is_code(self):
        from app.core.security_scan.normalizer import normalize_code_result
        result = normalize_code_result({})
        assert result["type"] == "code"

    def test_missing_location_fields_handled_gracefully(self):
        from app.core.security_scan.normalizer import normalize_code_result
        raw = {
            "runs": [{
                "results": [{
                    "ruleId": "X",
                    "level": "warning",
                    "message": {"text": "test"},
                    "locations": [{}]  # ไม่มี physicalLocation
                }]
            }]
        }
        result = normalize_code_result(raw)
        assert result["issues_found"] == 1
        loc = result["issues"][0]["locations"][0]
        assert loc["file"] is None
        assert loc["startLine"] is None