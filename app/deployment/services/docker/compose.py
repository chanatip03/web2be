"""Generate docker-compose.yml for multi-service deployments.

Uses dynamic host ports (random free ports) so multiple projects can run
simultaneously without port conflicts.
"""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DB_IMAGES = {
    "postgresql": "postgres:16-alpine",
    "postgres": "postgres:16-alpine",
    "mysql": "mysql:8.0",
    "mariadb": "mariadb:11",
    "mongodb": "mongo:7",
    "mongo": "mongo:7",
    "redis": "redis:7-alpine",
}

_DB_ENV = {
    "postgresql": {
        "POSTGRES_USER": "app",
        "POSTGRES_PASSWORD": "app_secret",
        "POSTGRES_DB": "app_db",
    },
    "postgres": {
        "POSTGRES_USER": "app",
        "POSTGRES_PASSWORD": "app_secret",
        "POSTGRES_DB": "app_db",
    },
    "mysql": {
        "MYSQL_ROOT_PASSWORD": "root_secret",
        "MYSQL_DATABASE": "app_db",
        "MYSQL_USER": "app",
        "MYSQL_PASSWORD": "app_secret",
    },
    "mariadb": {
        "MYSQL_ROOT_PASSWORD": "root_secret",
        "MYSQL_DATABASE": "app_db",
        "MYSQL_USER": "app",
        "MYSQL_PASSWORD": "app_secret",
    },
    "mongodb": {"MONGO_INITDB_ROOT_USERNAME": "app", "MONGO_INITDB_ROOT_PASSWORD": "app_secret"},
    "mongo": {"MONGO_INITDB_ROOT_USERNAME": "app", "MONGO_INITDB_ROOT_PASSWORD": "app_secret"},
    "redis": {},
}

_DB_PORTS = {
    "postgresql": 5432,
    "postgres": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mongodb": 27017,
    "mongo": 27017,
    "redis": 6379,
}

# Volume mount path per DB type
_DB_VOLUMES = {
    "postgresql": "/var/lib/postgresql/data",
    "postgres": "/var/lib/postgresql/data",
    "mysql": "/var/lib/mysql",
    "mariadb": "/var/lib/mysql",
    "mongodb": "/data/db",
    "mongo": "/data/db",
    "redis": "/data",
}


def _find_free_port() -> int:
    """Find an available host port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def generate_compose_yaml(
    *,
    project_name: str,
    backend_image: str,
    backend_port: int = 8000,
    frontend_image: Optional[str] = None,
    frontend_port: int = 3000,
    database_type: Optional[str] = None,
    db_init_sql: Optional[str] = None,
    db_ephemeral: bool = False,
    db_tmpfs_size: str = "512m",
    environment: Dict[str, str] | None = None,
) -> Tuple[str, Dict[str, Dict[str, int]]]:
    """Produce a docker-compose YAML string with dynamic host ports.

    Returns:
        (yaml_string, port_map)
        port_map: {"backend": {"container": 8000, "host": 54321}, ...}
    """
    port_map: Dict[str, Dict[str, int]] = {}
    lines = [
        f"# Auto-generated for {project_name}",
        "services:",
    ]

    # ── Backend service ──────────────────────────────────
    backend_host_port = _find_free_port()
    port_map["backend"] = {"container": backend_port, "host": backend_host_port}

    lines += [
        "  backend:",
        f"    image: {backend_image}",
        "    ports:",
        f'      - "{backend_host_port}:{backend_port}"',
    ]

    # Some backends (notably Go apps using godotenv) crash if `.env` is missing,
    # even when all configuration is provided via environment variables.
    # We mount a generated `.env.deployer` into the container's `/app/.env`.
    # The builder ensures `.env.deployer` exists (at least empty) for non-frontend modes.
    lines += [
        "    volumes:",
        '      - "./.env.deployer:/app/.env:ro"',
    ]
    merged_env = dict(environment or {})
    # Keep the app listen port consistent with the container port mapping.
    # This also prevents `.env` files (mounted for compatibility) from changing
    # the effective port and breaking proxy routing.
    merged_env.setdefault("PORT", str(backend_port))
    if merged_env:
        lines.append("    environment:")
        for k, v in merged_env.items():
            lines.append(f'      {k}: "{v}"')

    # Add DB connection env vars automatically
    if database_type:
        db_type = database_type.lower()
        if not merged_env:
            lines.append("    environment:")
        if db_type in ("postgresql", "postgres"):
            merged_env.setdefault("DATABASE_URL", "postgresql://app:app_secret@db:5432/app_db")
        elif db_type == "mysql":
            merged_env.setdefault("DATABASE_URL", "mysql://app:app_secret@db:3306/app_db")
            merged_env.setdefault("DB_HOST", "db")
            merged_env.setdefault("DB_USER", "app")
            merged_env.setdefault("DB_PASSWORD", "app_secret")
            merged_env.setdefault("DB_NAME", "app_db")
        elif db_type == "mariadb":
            merged_env.setdefault("DATABASE_URL", "mysql://app:app_secret@db:3306/app_db")
            merged_env.setdefault("DB_HOST", "db")
            merged_env.setdefault("DB_USER", "app")
            merged_env.setdefault("DB_PASSWORD", "app_secret")
            merged_env.setdefault("DB_NAME", "app_db")
        elif db_type in ("mongodb", "mongo"):
            merged_env.setdefault("DATABASE_URL", "mongodb://app:app_secret@db:27017/app_db?authSource=admin")
            merged_env.setdefault("MONGODB_URI", "mongodb://app:app_secret@db:27017/app_db?authSource=admin")
            merged_env.setdefault("DB_NAME", "app_db")
        elif db_type == "redis":
            merged_env.setdefault("REDIS_URL", "redis://db:6379")

        for k, v in merged_env.items():
            if any(line.strip().startswith(f"{k}:") for line in lines):
                continue
            lines.append(f'      {k}: "{v}"')

    depends_on = []
    if database_type:
        depends_on.append("db")
    if depends_on:
        lines.append("    depends_on:")
        for dep in depends_on:
            lines.append(f"      {dep}:")
            # DB readiness matters. Many apps run migrations/DDL at startup and
            # fail permanently if the DB isn't accepting connections yet.
            lines.append(f"        condition: service_healthy")

    lines.append("    restart: unless-stopped")
    lines.append(f"    networks:")
    lines.append(f"      - {project_name}-net")

    # ── Frontend service ─────────────────────────────────
    if frontend_image:
        frontend_host_port = _find_free_port()
        port_map["frontend"] = {"container": frontend_port, "host": frontend_host_port}

        lines += [
            "",
            "  frontend:",
            f"    image: {frontend_image}",
            "    ports:",
            f'      - "{frontend_host_port}:{frontend_port}"',
            "    depends_on:",
            "      backend:",
            "        condition: service_started",
            "    restart: unless-stopped",
            f"    networks:",
            f"      - {project_name}-net",
        ]

    # ── Database service ─────────────────────────────────
    if database_type:
        db_type = database_type.lower()
        db_image = _DB_IMAGES.get(db_type, f"{db_type}:latest")
        db_container_port = _DB_PORTS.get(db_type, 5432)
        db_host_port = _find_free_port()
        db_env = dict(_DB_ENV.get(db_type, {}))
        db_vol = _DB_VOLUMES.get(db_type, "/var/lib/data")

        # For MySQL-family DBs, keep db service env consistent with backend env
        # so the created database/user has privileges that match app settings.
        if db_type in {"mysql", "mariadb"}:
            desired_db = (
                (environment or {}).get("DB_NAME")
                or (environment or {}).get("MYSQL_DATABASE")
                or db_env.get("MYSQL_DATABASE")
            )
            desired_user = (
                (environment or {}).get("DB_USER")
                or (environment or {}).get("MYSQL_USER")
                or db_env.get("MYSQL_USER")
            )
            desired_pw = (
                (environment or {}).get("DB_PASSWORD")
                or (environment or {}).get("MYSQL_PASSWORD")
                or db_env.get("MYSQL_PASSWORD")
            )
            desired_root_pw = (
                (environment or {}).get("MYSQL_ROOT_PASSWORD")
                or (environment or {}).get("DB_ROOT_PASSWORD")
                or db_env.get("MYSQL_ROOT_PASSWORD")
            )

            if desired_db:
                db_env["MYSQL_DATABASE"] = str(desired_db)
            if desired_user:
                db_env["MYSQL_USER"] = str(desired_user)
            if desired_pw:
                db_env["MYSQL_PASSWORD"] = str(desired_pw)
            if desired_root_pw:
                db_env["MYSQL_ROOT_PASSWORD"] = str(desired_root_pw)

        port_map["db"] = {"container": db_container_port, "host": db_host_port}

        lines += [
            "",
            "  db:",
            f"    image: {db_image}",
        ]

        # DB healthchecks allow backend depends_on: service_healthy.
        if db_type in ("postgresql", "postgres"):
            lines += [
                "    healthcheck:",
                '      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-app} -d ${POSTGRES_DB:-app_db}"]',
                "      interval: 5s",
                "      timeout: 5s",
                "      retries: 20",
            ]
        elif db_type in ("mysql", "mariadb"):
            lines += [
                "    healthcheck:",
                '      test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -uroot -p${MYSQL_ROOT_PASSWORD:-root_secret}"]',
                "      interval: 5s",
                "      timeout: 5s",
                "      retries: 30",
            ]
        elif db_type in ("mongodb", "mongo"):
            lines += [
                "    healthcheck:",
                "      test: [\"CMD-SHELL\", \"mongosh --quiet --eval 'db.runCommand({ ping: 1 })' > /dev/null\"]",
                "      interval: 5s",
                "      timeout: 5s",
                "      retries: 30",
            ]
        elif db_type == "redis":
            lines += [
                "    healthcheck:",
                '      test: ["CMD", "redis-cli", "ping"]',
                "      interval: 5s",
                "      timeout: 3s",
                "      retries: 30",
            ]

        # Ensure UTF-8 correctness for projects seeding multilingual data.
        # Without this, MySQL may interpret UTF-8 seed scripts as latin1 and
        # store mojibake (e.g., Thai text becomes 'à¸...').
        if db_type == "mysql":
            lines += [
                "    command:",
                "      - --character-set-server=utf8mb4",
                "      - --collation-server=utf8mb4_0900_ai_ci",
                "      - --skip-character-set-client-handshake",
            ]
        elif db_type == "mariadb":
            lines += [
                "    command:",
                "      - --character-set-server=utf8mb4",
                "      - --collation-server=utf8mb4_unicode_ci",
                "      - --skip-character-set-client-handshake",
            ]

        lines += [
            "    ports:",
            f'      - "{db_host_port}:{db_container_port}"',
        ]
        if db_env:
            lines.append("    environment:")
            for k, v in db_env.items():
                lines.append(f'      {k}: "{v}"')
        if db_ephemeral:
            lines += [
                "    tmpfs:",
                f"      - {db_vol}:size={db_tmpfs_size}",
            ]
        else:
            lines += [
                "    volumes:",
                f"      - db_data:{db_vol}",
            ]

        if db_init_sql:
            # Ensure the init script is always mounted, regardless of persistence mode.
            if not db_ephemeral:
                # volumes section already started above
                lines.append(f"      - {db_init_sql}:/docker-entrypoint-initdb.d/seed.sql:ro")
            else:
                # tmpfs mode still needs a bind mount for seed.sql
                lines += [
                    "    volumes:",
                    f"      - {db_init_sql}:/docker-entrypoint-initdb.d/seed.sql:ro",
                ]

        lines += [
            "    restart: unless-stopped",
            f"    networks:",
            f"      - {project_name}-net",
        ]

    # ── Networks ─────────────────────────────────────────
    lines += [
        "",
        "networks:",
        f"  {project_name}-net:",
        "    driver: bridge",
    ]

    # ── Volumes ──────────────────────────────────────────
    if database_type and not db_ephemeral:
        lines += [
            "",
            "volumes:",
            "  db_data:",
        ]

    return "\n".join(lines) + "\n", port_map
