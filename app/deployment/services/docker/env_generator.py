"""Environment variable generator — creates .env from project analysis.

If the project has a .env or .env.example, use that as base.
Otherwise, scan source code via LLM to generate one with mock values.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.deployment.models.project import ProjectAnalysis

logger = logging.getLogger(__name__)

# Common env vars per DB type with Docker-internal hostnames
_DB_ENV_DEFAULTS = {
    "postgresql": {
        "DATABASE_URL": "postgresql://app:app_secret@db:5432/app_db",
        "POSTGRES_USER": "app",
        "POSTGRES_PASSWORD": "app_secret",
        "POSTGRES_DB": "app_db",
    },
    "postgres": {
        "DATABASE_URL": "postgresql://app:app_secret@db:5432/app_db",
        "POSTGRES_USER": "app",
        "POSTGRES_PASSWORD": "app_secret",
        "POSTGRES_DB": "app_db",
    },
    "mysql": {
        "DATABASE_URL": "mysql://app:app_secret@db:3306/app_db",
        "MYSQL_ROOT_PASSWORD": "root_secret",
        "MYSQL_DATABASE": "app_db",
        "MYSQL_USER": "app",
        "MYSQL_PASSWORD": "app_secret",
    },
    "mongodb": {
        "DATABASE_URL": "mongodb://app:app_secret@db:27017/app_db",
        "MONGO_INITDB_ROOT_USERNAME": "app",
        "MONGO_INITDB_ROOT_PASSWORD": "app_secret",
    },
    "redis": {
        "REDIS_URL": "redis://db:6379",
    },
}

# Common env vars per language/framework
_FRAMEWORK_ENV_DEFAULTS = {
    "fastapi": {"ENVIRONMENT": "production", "DEBUG": "false"},
    "django": {
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": "dev-secret-key-change-me-in-production",
        "DEBUG": "False",
        "ALLOWED_HOSTS": "*",
    },
    "flask": {
        "FLASK_ENV": "production",
        "SECRET_KEY": "dev-secret-key-change-me-in-production",
    },
    "express": {"NODE_ENV": "production"},
    "nestjs": {"NODE_ENV": "production"},
    "laravel": {
        "APP_ENV": "production",
        "APP_KEY": "base64:dGVzdC1rZXktY2hhbmdlLW1lLWluLXByb2R1Y3Rpb24=",
        "APP_DEBUG": "false",
    },
    "spring-boot": {
        "SPRING_PROFILES_ACTIVE": "production",
        "SERVER_PORT": "8000",
    },
}


def find_existing_env(project_path: Path) -> Optional[str]:
    """Look for existing .env or .env.example in the project."""
    for name in (".env", ".env.local", ".env.production", ".env.example", ".env.sample"):
        p = project_path / name
        if p.exists() and p.stat().st_size > 0:
            content = p.read_text(encoding="utf-8", errors="replace")
            logger.info("Found existing env file: %s", name)
            return content
    return None


def scan_env_vars_from_code(project_path: Path) -> list[str]:
    """Quick heuristic scan for env variable names in source files."""
    patterns = [
        re.compile(r'process\.env\.(\w+)'),
        re.compile(r'os\.environ\[[\"\'](\w+)[\"\']\]'),
        re.compile(r'os\.getenv\([\"\'](\w+)[\"\']'),
        re.compile(r'env\([\"\'](\w+)[\"\']'),
        re.compile(r'getenv\([\"\'](\w+)[\"\']'),
        re.compile(r'ENV\[[\"\'](\w+)[\"\']\]'),
        re.compile(r'@Value\(\"\$\{(\w+)'),
        re.compile(r'config\([\"\'](\w+)[\"\']'),
    ]

    found = set()
    extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".php", ".go", ".rb", ".env.example"}

    for f in project_path.rglob("*"):
        if f.is_file() and f.suffix in extensions and "node_modules" not in str(f):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")[:50000]
                for pat in patterns:
                    found.update(pat.findall(text))
            except Exception:
                continue

    # Filter out common noise
    noise = {"NODE_ENV", "HOME", "PATH", "PWD", "USER", "SHELL", "TERM"}
    return sorted(found - noise)


def _mock_value(var_name: str) -> str:
    """Generate a realistic mock value based on variable name."""
    name = var_name.upper()

    # Docker-compose internal hostnames (service name) for DBs.
    # Many apps use DB_HOST/MYSQL_HOST; defaulting these to 0.0.0.0 breaks
    # container-to-container networking.
    if "DB_HOST" in name or "MYSQL_HOST" in name or "POSTGRES_HOST" in name or "MONGO_HOST" in name or "REDIS_HOST" in name:
        return "db"

    if "PORT" in name:
        return "8000"
    if "SECRET" in name or "KEY" in name:
        return "dev-secret-key-change-me-in-production"
    if "PASSWORD" in name or "PASSWD" in name:
        return "app_secret"
    if "DATABASE_URL" in name or "DB_URL" in name:
        return "postgresql://app:app_secret@db:5432/app_db"
    if "REDIS" in name:
        return "redis://db:6379"
    if "MONGO" in name:
        return "mongodb://app:app_secret@db:27017/app_db"
    if "HOST" in name:
        return "0.0.0.0"
    if "DEBUG" in name:
        return "false"
    if "URL" in name or "URI" in name:
        return "http://localhost:8000"
    if "EMAIL" in name:
        return "admin@example.com"
    if "USER" in name or "USERNAME" in name:
        return "app"
    if "TOKEN" in name:
        return "dev-token-change-me"
    if "ENV" in name or "ENVIRONMENT" in name or "MODE" in name:
        return "production"
    return "changeme"


def generate_env_heuristic(
    project_path: Path,
    analysis: Optional[ProjectAnalysis] = None,
) -> str:
    """Generate a .env file using heuristic analysis (no LLM needed)."""
    lines = ["# Auto-generated environment variables for Docker deployment"]
    env_vars: Dict[str, str] = {}

    # 1. If existing .env/.env.example exists, use it as base
    existing = find_existing_env(project_path)
    if existing:
        lines.append("# Based on existing env file from repository")
        # Parse existing but fill empty values
        for line in existing.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                lines.append(line)
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if not val or val in ("", "your_value_here", "changeme", "xxx"):
                    val = _mock_value(key)
                env_vars[key] = val
                lines.append(f"{key}={val}")
        return "\n".join(lines) + "\n"

    # 2. Add framework defaults
    if analysis:
        be = analysis.backend_info or {}
        framework = be.get("framework", "")
        if framework and framework in _FRAMEWORK_ENV_DEFAULTS:
            lines.append(f"\n# {framework} defaults")
            for k, v in _FRAMEWORK_ENV_DEFAULTS[framework].items():
                if k not in env_vars:
                    env_vars[k] = v
                    lines.append(f"{k}={v}")

        # DB defaults
        db = analysis.database_info or {}
        if db.get("detected"):
            db_type = (db.get("type") or "postgresql").lower()
            db_env = _DB_ENV_DEFAULTS.get(db_type, {})
            lines.append(f"\n# {db_type} database")
            for k, v in db_env.items():
                if k not in env_vars:
                    env_vars[k] = v
                    lines.append(f"{k}={v}")

        # Env vars from analysis
        env_list = analysis.environment_variables or []
        if env_list:
            lines.append("\n# Detected from code")
            for var in env_list:
                if var not in env_vars:
                    env_vars[var] = _mock_value(var)
                    lines.append(f"{var}={env_vars[var]}")

    # 3. Scan source code for additional env vars
    scanned = scan_env_vars_from_code(project_path)
    new_vars = [v for v in scanned if v not in env_vars]
    if new_vars:
        lines.append("\n# Scanned from source code")
        for var in new_vars[:30]:  # limit
            env_vars[var] = _mock_value(var)
            lines.append(f"{var}={env_vars[var]}")

    return "\n".join(lines) + "\n"


async def generate_env_with_llm(
    project_path: Path,
    analysis: ProjectAnalysis,
    file_tree: str,
    file_samples: str,
) -> str:
    """Generate .env using LLM for smarter variable detection.

    LLM-only mode: raises on failure (no heuristic fallback).
    """
    from app.deployment.services.llm.client import llm_client
    from app.deployment.services.llm.prompts import ENV_GEN_SYSTEM, ENV_GEN_USER
    import json

    try:
        analysis_str = json.dumps(analysis.model_dump(), default=str, indent=2)
    except Exception:
        analysis_str = str(analysis)

    user_prompt = ENV_GEN_USER.format(
        analysis=analysis_str,
        file_tree=file_tree,
        file_samples=file_samples,
    )

    try:
        result = await llm_client.chat(
            [
                {"role": "system", "content": ENV_GEN_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            step="env_generation",
        )

        # Clean up markdown fences if present
        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        return result.strip() + "\n"

    except Exception as exc:
        logger.error("LLM env generation failed: %s", exc)
        raise
