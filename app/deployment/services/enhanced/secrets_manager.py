"""Secrets manager — Fernet encryption for sensitive environment variables."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.deployment.core.config import settings

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None  # type: ignore[assignment,misc]


# Keys that are considered sensitive and will be auto-encrypted
_SENSITIVE_PATTERNS = {
    "password", "secret", "key", "token", "api_key",
    "database_url", "db_password", "jwt_secret", "private",
}


class SecretsManager:
    """Encrypt/decrypt secrets and manage per-deployment secret storage."""

    def __init__(self):
        self._key = self._get_or_create_key()
        self._cipher = Fernet(self._key) if self._key and Fernet else None

    def _get_or_create_key(self) -> Optional[bytes]:
        if Fernet is None:
            logger.warning("cryptography package not installed — secrets stored in plain text")
            return None

        key_file = Path(settings.deployments_dir) / ".secrets_key"
        if key_file.exists():
            return key_file.read_bytes()

        key = Fernet.generate_key()
        key_file.write_bytes(key)
        try:
            key_file.chmod(0o600)
        except Exception:
            pass
        return key

    def encrypt(self, value: str) -> str:
        if not self._cipher:
            return value
        encrypted = self._cipher.encrypt(value.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, value: str) -> str:
        if not self._cipher:
            return value
        try:
            decoded = base64.b64decode(value.encode())
            return self._cipher.decrypt(decoded).decode()
        except Exception:
            return value

    def encrypt_env(self, env_vars: Dict[str, str]) -> Dict[str, str]:
        """Auto-encrypt values whose keys look sensitive."""
        result = {}
        for key, val in env_vars.items():
            if any(p in key.lower() for p in _SENSITIVE_PATTERNS):
                result[key] = self.encrypt(val)
            else:
                result[key] = val
        return result

    def decrypt_env(self, env_vars: Dict[str, str]) -> Dict[str, str]:
        return {k: self.decrypt(v) for k, v in env_vars.items()}

    def save(self, deployment_id: str, secrets: Dict[str, str]) -> None:
        secrets_dir = Path(settings.deployments_dir) / deployment_id / "secrets"
        secrets_dir.mkdir(parents=True, exist_ok=True)
        encrypted = self.encrypt_env(secrets)
        path = secrets_dir / "secrets.enc.json"
        path.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")
        try:
            path.chmod(0o600)
        except Exception:
            pass

    def load(self, deployment_id: str) -> Dict[str, str]:
        path = Path(settings.deployments_dir) / deployment_id / "secrets" / "secrets.enc.json"
        if not path.exists():
            return {}
        try:
            encrypted = json.loads(path.read_text(encoding="utf-8"))
            return self.decrypt_env(encrypted)
        except Exception:
            return {}


secrets_manager = SecretsManager()
