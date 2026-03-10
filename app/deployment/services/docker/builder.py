"""Docker build + run orchestrator — mode-aware multi-service deployment.

Supports 3 deploy modes:
- frontend-only:  1 service (frontend container)
- backend-only:   1-2 services (backend + optional DB via compose)
- fullstack:      2-3 services (frontend + backend + optional DB via compose)

After successful deployment, images are saved as .tar.gz for portability.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from app.deployment.core.config import settings
from app.deployment.core.exceptions import DockerError
from app.deployment.models.deployment import DeploymentConfig
from app.deployment.models.project import ProjectAnalysis
from app.deployment.services.analyzer.file_scanner import build_file_tree, sample_key_files
from app.deployment.services.docker.adaptation_registry import AdaptationContext, create_default_registry
from app.deployment.services.docker.client import docker_client
from app.deployment.services.docker.compose import generate_compose_yaml
from app.deployment.services.docker.generator import docker_generator

logger = logging.getLogger(__name__)


class DockerBuilder:
    """Orchestrate: analyse mode → generate Dockerfiles → build images → run."""

    def __init__(self) -> None:
        self._adaptation_registry = create_default_registry()

    def _safe_write(self, file_path: Path, content: str) -> bool:
        try:
            file_path.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def _build_healthcheck_probe_cmd(self, port: int) -> str:
        acceptable = {"200", "201", "202", "204", "301", "302", "307", "308", "401", "403", "404", "405"}
        allowed_expr = "|".join(sorted(acceptable))
        paths = ["/health", "/healthz", "/status", "/ping", "/"]
        probe_parts = []
        for p in paths:
            probe_parts.append(
                f"code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{int(port)}{p} || true); "
                f"echo \"$code\" | grep -Eq '^({allowed_expr})$' && exit 0"
            )
        return " || ".join(f"( {part} )" for part in probe_parts) + " || exit 1"

    def _strip_existing_healthcheck(self, dockerfile_content: str) -> str:
        lines = dockerfile_content.splitlines()
        out: list[str] = []
        skip = False
        for line in lines:
            if not skip and re.match(r"(?im)^\s*HEALTHCHECK\b", line):
                skip = bool(line.rstrip().endswith("\\"))
                continue
            if skip:
                skip = bool(line.rstrip().endswith("\\"))
                continue
            out.append(line)
        content = "\n".join(out)
        if dockerfile_content.endswith("\n"):
            content += "\n"
        return content

    def _apply_healthcheck_policy(self, dockerfile_content: str, container_port: Optional[int]) -> str:
        port = int(container_port or 8000)
        content = self._strip_existing_healthcheck(dockerfile_content)
        healthcheck_lines = [
            "HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=12 \\",
            f"  CMD {self._build_healthcheck_probe_cmd(port)}",
        ]

        lines = content.splitlines()
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if re.match(r"(?im)^\s*CMD\b", line) or re.match(r"(?im)^\s*ENTRYPOINT\b", line):
                insert_at = i
                break
        lines[insert_at:insert_at] = healthcheck_lines
        out = "\n".join(lines)
        if not out.endswith("\n"):
            out += "\n"
        return out

    def _auto_adapt_frontend_files(self, project_path: Path, analysis: Optional[ProjectAnalysis]) -> list[str]:
        changed: list[str] = []
        frontend_path = str((analysis.frontend_info or {}).get("path") or "frontend").strip() if analysis else "frontend"
        roots = [project_path / frontend_path, project_path]

        vite_candidates = [
            "vite.config.ts",
            "vite.config.js",
            "vite.config.mjs",
            "vite.config.cjs",
        ]
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for rel in vite_candidates:
                file_path = root / rel
                if not file_path.exists() or not file_path.is_file():
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                new_text = re.sub(
                    r"(?m)^\s*base\s*:\s*['\"][^'\"]+['\"]\s*,?\s*$",
                    "  base: './',",
                    text,
                )
                if new_text != text and self._safe_write(file_path, new_text):
                    changed.append(str(file_path.relative_to(project_path)))

        app_candidates = []
        for root in roots:
            src_dir = root / "src"
            if src_dir.exists() and src_dir.is_dir():
                for rel in ("App.tsx", "App.jsx", "App.ts", "App.js"):
                    app_candidates.append(src_dir / rel)

        for file_path in app_candidates:
            if not file_path.exists() or not file_path.is_file():
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            new_text = re.sub(
                r"<BrowserRouter\s+basename=(\"[^\"]*\"|'[^']*'|\{[^}]*\})\s*>",
                "<BrowserRouter>",
                text,
            )
            if new_text != text and self._safe_write(file_path, new_text):
                changed.append(str(file_path.relative_to(project_path)))

        return changed

    def _auto_adapt_node_backend_files(self, project_path: Path, analysis: Optional[ProjectAnalysis]) -> list[str]:
        changed: list[str] = []
        backend_path = str((analysis.backend_info or {}).get("path") or "backend").strip() if analysis else "backend"
        roots = [project_path / backend_path, project_path]

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for ext in ("*.js", "*.ts", "*.mjs", "*.cjs"):
                for file_path in root.rglob(ext):
                    if "node_modules" in file_path.parts:
                        continue
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    if "mysql.createConnection" not in text and "mysql.createPool" not in text:
                        continue

                    new_text = text
                    new_text = re.sub(
                        r"host\s*:\s*['\"](?:localhost|127\.0\.0\.1|::1)['\"]",
                        "host: process.env.DB_HOST || 'db'",
                        new_text,
                    )
                    if "process.env.DB_USER" not in new_text:
                        new_text = re.sub(
                            r"user\s*:\s*['\"][^'\"]+['\"]",
                            "user: process.env.DB_USER || process.env.MYSQL_USER || 'app'",
                            new_text,
                            count=1,
                        )
                    if "process.env.DB_PASSWORD" not in new_text:
                        new_text = re.sub(
                            r"password\s*:\s*['\"][^'\"]*['\"]",
                            "password: process.env.DB_PASSWORD || process.env.MYSQL_PASSWORD || 'app_secret'",
                            new_text,
                            count=1,
                        )
                    new_text = re.sub(
                        r"process\.env\.DB_PASS\b",
                        "process.env.DB_PASSWORD || process.env.DB_PASS",
                        new_text,
                    )
                    if "process.env.DB_NAME" not in new_text:
                        new_text = re.sub(
                            r"database\s*:\s*['\"][^'\"]+['\"]",
                            "database: process.env.DB_NAME || process.env.MYSQL_DATABASE || 'app_db'",
                            new_text,
                            count=1,
                        )

                    if "process.env.PORT" not in new_text:
                        new_text = re.sub(
                            r"const\s+port\s*=\s*(\d+)\s*;",
                            r"const port = Number(process.env.PORT || \1);",
                            new_text,
                            count=1,
                        )

                    if new_text != text and self._safe_write(file_path, new_text):
                        changed.append(str(file_path.relative_to(project_path)))

        return changed

    def _auto_adapt_project_files(self, project_path: Path, analysis: Optional[ProjectAnalysis], mode: str) -> None:
        if not settings.deploy_auto_adapt_files:
            return
        try:
            ctx = AdaptationContext(project_path=project_path, analysis=analysis, mode=mode or "auto")
            changed = self._adaptation_registry.apply_all(ctx, self._safe_write)
            if changed:
                logger.info("Auto-adapted project files for deployment: %s", changed)
        except Exception as exc:
            logger.warning("Auto-adaptation skipped: %s", exc)

    def _read_node_dependencies(self, pkg_path: Path) -> Dict[str, str]:
        if not pkg_path.exists() or not pkg_path.is_file():
            return {}
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}

        deps: Dict[str, str] = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            block = data.get(key)
            if isinstance(block, dict):
                for name, ver in block.items():
                    if isinstance(name, str) and isinstance(ver, str):
                        deps[name] = ver
        return deps

    def _infer_db_type_from_node_deps(self, deps: Dict[str, str]) -> Optional[str]:
        names = {k.lower() for k in (deps or {}).keys()}
        if "mysql2" in names or "mysql" in names:
            return "mysql"
        if "pg" in names or "pg-promise" in names or "postgres" in names or "postgresql" in names:
            return "postgres"
        if "mongoose" in names or "mongodb" in names:
            return "mongodb"
        if "redis" in names or "ioredis" in names:
            return "redis"
        return None

    def _detect_database_info(self, project_path: Path, analysis: Optional[ProjectAnalysis]) -> Dict[str, Any]:
        """Use database detection from analysis only (LLM-first mode)."""
        return dict((analysis.database_info or {}) if analysis else {})

    def _inject_nginx_extra_assets(self, dockerfile_content: str, project_path: Path) -> str:
        """Include common asset directories into nginx static images when present.

        Some repos keep large assets (e.g. images) at the project root instead of
        inside the frontend folder. If we only copy `frontend/`, those assets are
        missing in the running nginx container.
        """
        content = dockerfile_content or ""
        lowered = content.lower()
        if "from nginx" not in lowered:
            return dockerfile_content

        # Only inject if assets exist in the build context.
        img_dir = project_path / "img_place"
        if not img_dir.exists() or not img_dir.is_dir():
            return dockerfile_content

        # Avoid duplicate injection.
        if re.search(r"(?im)^\s*copy\s+img_place/\s+", content):
            return dockerfile_content

        lines = content.splitlines()

        # Insert after the first COPY (typically copies frontend/) or after WORKDIR.
        insert_at = None
        for i, line in enumerate(lines):
            if re.match(r"(?i)^\s*copy\s+", line):
                insert_at = i + 1
                break
        if insert_at is None:
            for i, line in enumerate(lines):
                if re.match(r"(?i)^\s*workdir\s+", line):
                    insert_at = i + 1
                    break
        if insert_at is None:
            insert_at = len(lines)

        lines.insert(insert_at, "COPY img_place/ img_place/")

        out = "\n".join(lines)
        if dockerfile_content.endswith("\n"):
            out += "\n"
        return out

    def _prepare_mysql_seed_sql(self, project_path: Path, seed_mount: str) -> str:
        """Copy (and lightly sanitize) a MySQL seed SQL file into a stable path.

        Rationale:
        - Seed filenames can contain spaces, which are awkward in compose mounts.
        - Some projects ship schemas that reject their own inserts (e.g. DECIMAL(1,1)
          for values like 4.8). We apply minimal, safe widening.
        """
        if not seed_mount:
            return seed_mount

        rel = seed_mount
        if rel.startswith("./"):
            rel = rel[2:]
        seed_abs = (project_path / rel).resolve()
        if not seed_abs.exists() or not seed_abs.is_file():
            return seed_mount

        try:
            sql = seed_abs.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return seed_mount

        # Minimal sanitization: widen tiny decimals that commonly break imports.
        sanitized = sql

        # Make schema creation idempotent. The official MySQL image may create
        # MYSQL_DATABASE before running init scripts; a plain CREATE SCHEMA then
        # aborts the whole init.
        sanitized = re.sub(
            r"(?im)^\s*create\s+(schema|database)\s+([a-zA-Z0-9_]+)\s*;\s*$",
            r"CREATE \1 IF NOT EXISTS \2;",
            sanitized,
        )

        sanitized = re.sub(
            r"(?i)\b(decimal|numeric)\s*\(\s*1\s*,\s*1\s*\)",
            "DECIMAL(3,1)",
            sanitized,
        )

        # Widen undersized VARCHAR columns that commonly break on real-world Thai strings.
        sanitized = re.sub(
            r"(?im)^(\s*place_name\s+)varchar\s*\(\s*50\s*\)",
            r"\1varchar(255)",
            sanitized,
        )
        sanitized = re.sub(
            r"(?im)^(\s*place_province\s+)varchar\s*\(\s*20\s*\)",
            r"\1varchar(255)",
            sanitized,
        )
        sanitized = re.sub(
            r"(?im)^(\s*place_eng_province\s+)varchar\s*\(\s*50\s*\)",
            r"\1varchar(100)",
            sanitized,
        )

        # If the seed adds a NOT NULL column after inserts are written without it,
        # MySQL strict mode will fail. Ensure the added column has a default.
        sanitized = re.sub(
            r"(?im)^\s*alter\s+table\s+place\s+add\s+place_eng_province\s+varchar\s*\(\s*\d+\s*\)\s+not\s+null\s*;",
            "ALTER TABLE place ADD place_eng_province VARCHAR(100) NOT NULL DEFAULT '';",
            sanitized,
        )

        # Some seeds incorrectly try to update a column using `SET ... WHERE ...`.
        # In MySQL, `SET` assigns variables, not table columns; this aborts the
        # import and later inserts (e.g. place_images) never run.
        sanitized = re.sub(
            r"(?im)^\s*set\s+place_eng_province\s*=\s*case\s+place_province\b",
            "UPDATE place SET place_eng_province = CASE place_province",
            sanitized,
        )

        # Ensure the init client interprets this script as UTF-8.
        # Without this, multilingual strings (e.g. Thai) can be imported as latin1
        # and become mojibake in the DB.
        if not re.search(r"(?im)^\s*set\s+names\s+utf8mb4\s*;", sanitized):
            header = (
                "SET NAMES utf8mb4;\n"
                "SET CHARACTER SET utf8mb4;\n"
                "SET collation_connection = 'utf8mb4_unicode_ci';\n\n"
            )
            sanitized = header + sanitized.lstrip("\ufeff")

        # Some seeds are not topologically ordered for foreign keys.
        # If an early FK insert fails, MySQL aborts the script and later inserts
        # (including image tables) never run. Disable FK checks for the import.
        if not re.search(r"(?im)^\s*set\s+foreign_key_checks\s*=\s*0\s*;", sanitized):
            sanitized = "SET FOREIGN_KEY_CHECKS=0;\n" + sanitized

        # Re-enable at end (best-effort). MySQL does not retro-validate existing rows.
        if not re.search(r"(?im)^\s*set\s+foreign_key_checks\s*=\s*1\s*;\s*$", sanitized):
            sanitized = sanitized.rstrip() + "\n\nSET FOREIGN_KEY_CHECKS=1;\n"

        out_dir = project_path / ".deploy"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "seed.sql"

        try:
            out_path.write_text(sanitized, encoding="utf-8")
        except Exception:
            return seed_mount

        return "./.deploy/seed.sql"

    def _apply_env_overrides(self, env_content: str, overrides: Dict[str, str]) -> str:
        lines = (env_content or "").splitlines()
        key_to_index: Dict[str, int] = {}

        for i, line in enumerate(lines):
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, _, _ = s.partition("=")
            key = key.strip()
            if key:
                key_to_index[key] = i

        for key, value in (overrides or {}).items():
            if value is None:
                continue
            if key in key_to_index:
                lines[key_to_index[key]] = f"{key}={value}"
            else:
                lines.append(f"{key}={value}")

        # Keep legacy DB_PASS aligned for Node backends using process.env.DB_PASS.
        refreshed_index: Dict[str, int] = {}
        for i, line in enumerate(lines):
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, _, _ = s.partition("=")
            key = key.strip()
            if key:
                refreshed_index[key] = i

        if "DB_PASSWORD" in refreshed_index:
            db_password_value = lines[refreshed_index["DB_PASSWORD"]].split("=", 1)[1]
            if "DB_PASS" in refreshed_index:
                lines[refreshed_index["DB_PASS"]] = f"DB_PASS={db_password_value}"
            else:
                lines.append(f"DB_PASS={db_password_value}")

        out = "\n".join(lines)
        if not out.endswith("\n"):
            out += "\n"
        return out

    def _read_package_scripts(self, root: Path) -> Dict[str, Any]:
        pkg = root / "package.json"
        if not pkg.exists():
            return {}
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
        scripts = data.get("scripts")
        return scripts if isinstance(scripts, dict) else {}

    def _read_package_json(self, root: Path) -> Dict[str, Any]:
        pkg = root / "package.json"
        if not pkg.exists():
            return {}
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _tsconfig_no_emit(self, root: Path) -> bool:
        tsconfig = root / "tsconfig.json"
        if not tsconfig.exists():
            return False
        try:
            data = json.loads(tsconfig.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        opts = data.get("compilerOptions")
        if not isinstance(opts, dict):
            return False
        return bool(opts.get("noEmit") is True)

    def _detect_ts_entrypoint(self, root: Path) -> Optional[str]:
        for rel in ("src/index.ts", "src/server.ts", "src/main.ts", "index.ts", "server.ts"):
            if (root / rel).exists():
                return rel
        return None

    def _choose_node_cmd(self, root: Path) -> Optional[List[str]]:
        scripts = self._read_package_scripts(root)
        pkg = self._read_package_json(root)
        start_script = scripts.get("start") if isinstance(scripts.get("start"), str) else ""

        # Some TS projects ship with `start: node dist/...` but tsconfig has `noEmit: true`.
        # In that case `npm start` will crash (dist never exists). Prefer running via tsx.
        if start_script and "dist/" in start_script and self._tsconfig_no_emit(root):
            entry = self._detect_ts_entrypoint(root)
            if entry:
                return ["npx", "tsx", entry]
            if "dev" in scripts:
                return ["npm", "run", "dev"]

        if "start" in scripts:
            return ["npm", "start"]
        if "dev" in scripts:
            return ["npm", "run", "dev"]
        for entry in ("server.js", "index.js", "app.js"):
            if (root / entry).exists():
                return ["node", entry]
        return None

    def _normalize_node_backend_cmd(self, dockerfile_content: str, root: Path, container_port: Optional[int] = None) -> str:
        desired = self._choose_node_cmd(root)
        if not desired:
            return dockerfile_content

        desired_cmd = "CMD " + json.dumps(desired)
        content = re.sub(r"(?m)^CMD\s+.*$", desired_cmd, dockerfile_content)
        if "CMD " not in content:
            content = content.rstrip() + "\n" + desired_cmd

        # If we switched to `tsx`, ensure dev deps are installed (tsx/typescript are typically devDependencies).
        if desired[:2] == ["npx", "tsx"]:
            content = re.sub(r"(?m)^(\s*RUN\s+npm\s+ci)\s+--only=production\s*$", r"\1", content)
            content = re.sub(r"(?m)^(\s*RUN\s+npm\s+ci)\s+--omit=dev\s*$", r"\1", content)
            content = re.sub(r"(?m)^(\s*RUN\s+npm\s+ci)\s+--only\s*=\s*production\s*$", r"\1", content)
            content = re.sub(r"(?m)^(\s*RUN\s+npm\s+ci)\s+--production\s*$", r"\1", content)

        # Keep EXPOSE/healthcheck ports aligned with what proxy/compose expects when known.
        if container_port:
            content = re.sub(r"(?m)^\s*EXPOSE\s+\d+\s*$", f"EXPOSE {int(container_port)}", content)
            content = re.sub(
                r"(?m)(curl\s+-f\s+http://localhost:)(\d+)",
                rf"\g<1>{int(container_port)}",
                content,
            )

        # If we run as a non-root user, ensure the working directory is writable.
        # Many apps try to write logs or temp files relative to WORKDIR (e.g. ./app.log).
        user_match = re.search(r"(?m)^\s*USER\s+([^\s#]+)\s*$", content)
        if user_match and "WORKDIR /app" in content:
            user = user_match.group(1)
            mkdir_chown = f"RUN mkdir -p /app/public/uploads && chown -R {user} /app"
            if mkdir_chown not in content:
                content = re.sub(r"(?m)^\s*USER\s+", mkdir_chown + "\nUSER ", content, count=1)

        # If healthcheck uses curl on alpine, make sure curl exists.
        if re.search(r"(?im)^\s*FROM\s+node:.*alpine\b", content) and "HEALTHCHECK" in content and "curl" in content:
            if not re.search(r"(?im)^\s*RUN\s+apk\s+add\b.*\bcurl\b", content):
                content = re.sub(
                    r"(?im)^(FROM\s+node:.*alpine\b.*)$",
                    r"\1\nRUN apk add --no-cache curl",
                    content,
                    count=1,
                )

        if dockerfile_content.endswith("\n"):
            content += "\n"
        return content

    def _harden_backend_dockerfile(self, dockerfile_content: str) -> str:
        """Harden backend Dockerfiles generated by the LLM.

        This is intentionally language-agnostic (Go/Node/Python/etc.).

        Fixes two common issues:
        1) Non-root USER + unwritable WORKDIR (e.g. apps writing ./app.log).
        2) HEALTHCHECK using curl on alpine images without installing curl.
        """

        def _process_stage(from_line: str, stage_lines: list[str]) -> list[str]:
            stage_is_alpine = bool(re.search(r"(?i)\balpine\b", from_line))

            has_curl_healthcheck = any(
                ("HEALTHCHECK" in ln and "curl" in ln) for ln in stage_lines
            )
            has_apk_curl = any(
                re.search(r"(?i)^\s*RUN\s+apk\s+add\b.*\bcurl\b", ln) for ln in stage_lines
            )

            out: list[str] = [from_line]
            if stage_is_alpine and has_curl_healthcheck and not has_apk_curl:
                out.append("RUN apk add --no-cache curl")

            last_workdir: Optional[str] = None
            inserted_chown_for: set[tuple[str, str]] = set()

            for ln in stage_lines:
                wd = re.match(r"(?m)^\s*WORKDIR\s+([^\s#]+)\s*$", ln)
                if wd:
                    last_workdir = wd.group(1)

                user_match = re.match(r"(?m)^\s*USER\s+([^\s#]+)\s*$", ln)
                if user_match and last_workdir:
                    user = user_match.group(1)
                    workdir = last_workdir

                    if user != "root" and workdir.startswith("/") and "$" not in workdir:
                        key = (user, workdir)
                        # Only consider explicit chown commands; COPY --chown fixes file ownership
                        # but does not make the WORKDIR itself writable for creating new files.
                        already_has_chown = any(
                            re.search(r"(?i)^\s*RUN\s+.*\bchown\b", s)
                            and workdir in s
                            and user in s
                            for s in out
                        ) or any(
                            re.search(r"(?i)^\s*RUN\s+.*\bchown\b", s)
                            and workdir in s
                            and user in s
                            for s in stage_lines
                        )

                        if key not in inserted_chown_for and not already_has_chown:
                            out.append(f"RUN mkdir -p {workdir} && chown -R {user} {workdir}")
                            inserted_chown_for.add(key)

                out.append(ln)

            return out

        lines = dockerfile_content.splitlines()
        stages: list[list[str]] = []
        current: list[str] = []
        for ln in lines:
            if re.match(r"(?i)^\s*FROM\s+", ln):
                if current:
                    stages.append(current)
                current = [ln]
            else:
                if not current:
                    # Dockerfile missing a FROM (invalid) — return unchanged.
                    return dockerfile_content
                current.append(ln)
        if current:
            stages.append(current)

        hardened_lines: list[str] = []
        for stage in stages:
            from_line = stage[0]
            stage_body = stage[1:]
            hardened_lines.extend(_process_stage(from_line, stage_body))

        hardened = "\n".join(hardened_lines)
        if dockerfile_content.endswith("\n"):
            hardened += "\n"
        return hardened

    def _ensure_runtime_dotenv_file(self, dockerfile_content: str) -> str:
        """Ensure a `.env` file exists in the final/runtime stage.

        Some backends (notably Go apps using godotenv) crash if `.env` is missing,
        even when all configuration is provided via environment variables.

        We avoid baking secrets into images by *not* copying `.env` contents.
        Instead, we create an empty file in the final stage when the Dockerfile
        doesn't already manage `.env`.
        """

        if not dockerfile_content:
            return dockerfile_content

        # If the Dockerfile already references `.env`, assume it's handled.
        if re.search(r"(?im)^\s*(COPY|ADD|RUN)\b.*\b\.env\b", dockerfile_content):
            return dockerfile_content

        lines = dockerfile_content.splitlines()
        from_idxs = [i for i, ln in enumerate(lines) if re.match(r"(?i)^\s*FROM\s+", ln)]
        if not from_idxs:
            return dockerfile_content

        # Only touch `.env` in the final stage.
        stage_start = from_idxs[-1]
        stage_end = len(lines)
        workdir_idx = None
        for i in range(stage_start + 1, stage_end):
            if re.match(r"(?i)^\s*WORKDIR\s+", lines[i]):
                workdir_idx = i
                break
        if workdir_idx is None:
            return dockerfile_content

        insert_at = workdir_idx + 1
        lines.insert(insert_at, "RUN test -f .env || touch .env")
        out = "\n".join(lines)
        if dockerfile_content.endswith("\n"):
            out += "\n"
        return out

    def _is_static_frontend(self, root: Path) -> bool:
        if (root / "package.json").exists():
            return False
        try:
            return next(root.rglob("*.html"), None) is not None
        except Exception:
            return False

    def _render_static_frontend_dockerfile(self, rel_path: str) -> str:
        copy_src = rel_path if rel_path else "."
        lines = [
            "FROM nginx:alpine",
            "WORKDIR /usr/share/nginx/html",
            "RUN rm -f /usr/share/nginx/html/index.html",
            f"COPY {copy_src}/ .",
            "RUN if [ ! -f /usr/share/nginx/html/index.html ]; then \\",
            "  target=\"\"; \\",
            "  for c in home/home.html landing.html home.html index.htm shop.html; do \\",
            "    if [ -f /usr/share/nginx/html/$c ]; then target=$c; break; fi; \\",
            "  done; \\",
            "  if [ -z \"$target\" ]; then \\",
            "    first=$(find /usr/share/nginx/html -maxdepth 2 -type f -name '*.html' 2>/dev/null | head -n 1); \\",
            "    if [ -n \"$first\" ]; then target=\"${first#/usr/share/nginx/html/}\"; fi; \\",
            "  fi; \\",
            "  if [ -n \"$target\" ]; then \\",
            "    printf '<!doctype html><meta http-equiv=\"refresh\" content=\"0; url=%s\">' \"$target\" > /usr/share/nginx/html/index.html; \\",
            "  fi; \\",
            "fi",
            "EXPOSE 80",
            "HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\",
            "  CMD curl -f http://localhost/ || exit 1",
            "CMD [\"nginx\", \"-g\", \"daemon off;\"]",
        ]
        return "\n".join(lines) + "\n"

    def _render_node_static_frontend_dockerfile(self, rel_path: str, port: int) -> str:
        copy_src = rel_path if rel_path else "."
        lines = [
            "FROM node:20-alpine",
            "RUN apk add --no-cache curl",
            "WORKDIR /app",
            f"COPY {copy_src}/package*.json ./",
            "RUN npm ci",
            f"COPY {copy_src}/ ./",
            "RUN if [ ! -f /app/index.html ]; then \\",
            "  target=\"\"; \\",
            "  for c in html/index.html index.htm html/login.html login.html; do \\",
            "    if [ -f /app/$c ]; then target=$c; break; fi; \\",
            "  done; \\",
            "  if [ -z \"$target\" ]; then \\",
            "    first=$(find /app -maxdepth 2 -type f -name '*.html' 2>/dev/null | head -n 1); \\",
            "    if [ -n \"$first\" ]; then target=\"${first#/app/}\"; fi; \\",
            "  fi; \\",
            "  if [ -n \"$target\" ]; then \\",
            "    printf '<!doctype html><meta http-equiv=\"refresh\" content=\"0; url=%s\">' \"$target\" > /app/index.html; \\",
            "  fi; \\",
            "fi",
            f"EXPOSE {int(port)}",
            "HEALTHCHECK --interval=10s --timeout=4s --start-period=15s --retries=12 \\",
            f"  CMD curl -sf http://127.0.0.1:{int(port)}/ || exit 1",
            f"CMD [\"npx\", \"http-server\", \".\", \"-p\", \"{int(port)}\"]",
        ]
        return "\n".join(lines) + "\n"

    def _is_nextjs_ssr_frontend(self, frontend_root: Path) -> bool:
        pkg = self._read_package_json(frontend_root)
        if not pkg:
            return False
        deps = pkg.get("dependencies") if isinstance(pkg.get("dependencies"), dict) else {}
        dev_deps = pkg.get("devDependencies") if isinstance(pkg.get("devDependencies"), dict) else {}
        has_next = "next" in deps or "next" in dev_deps
        scripts = self._read_package_scripts(frontend_root)
        start_script = str(scripts.get("start") or "").lower()
        build_script = str(scripts.get("build") or "").lower()
        return has_next and ("next start" in start_script) and ("next build" in build_script)

    def _render_nextjs_runtime_frontend_dockerfile(self, rel_path: str, port: int) -> str:
        copy_src = rel_path if rel_path else "."
        lines = [
            "FROM node:20-alpine",
            "RUN apk add --no-cache curl",
            "WORKDIR /app",
            f"COPY {copy_src}/package*.json ./",
            "RUN npm ci",
            f"COPY {copy_src}/ ./",
            f"ENV PORT={int(port)}",
            f"EXPOSE {int(port)}",
            "HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=12 \\",
            f"  CMD curl -sf http://127.0.0.1:{int(port)}/ || exit 1",
            f"CMD [\"sh\", \"-lc\", \"npm run build && npm run start -- -p {int(port)}\"]",
        ]
        return "\n".join(lines) + "\n"

    def _frontend_uses_buildless_runtime(self, frontend_root: Path) -> bool:
        scripts = self._read_package_scripts(frontend_root)
        if not scripts:
            return False
        has_build = isinstance(scripts.get("build"), str) and scripts.get("build", "").strip() != ""
        has_dev = isinstance(scripts.get("dev"), str) and scripts.get("dev", "").strip() != ""
        return (not has_build) and has_dev

    def _resolve_frontend_root(self, analysis: ProjectAnalysis, build_spec: Dict[str, Any], project_path: Path) -> tuple[str, Path]:
        candidates: list[str] = []
        fe_path = str((analysis.frontend_info or {}).get("path") or "").strip()
        if fe_path:
            candidates.append(fe_path)

        modules = build_spec.get("modules") if isinstance(build_spec, dict) else None
        if isinstance(modules, list):
            for m in modules:
                if not isinstance(m, dict):
                    continue
                if str(m.get("type") or "").lower() == "frontend":
                    p = str(m.get("path") or "").strip()
                    if p:
                        candidates.append(p)

        candidates.extend(["frontend", "client", "web", "."])

        seen: set[str] = set()
        for rel in candidates:
            rel_n = rel or "."
            if rel_n in seen:
                continue
            seen.add(rel_n)
            root = project_path / rel_n if rel_n != "." else project_path
            if not root.exists() or not root.is_dir():
                continue
            if (root / "package.json").exists() or (root / "index.html").exists():
                return rel_n, root

        return (fe_path or "frontend"), (project_path / (fe_path or "frontend"))

    def _extract_sql_schema_name(self, sql_path: Path) -> Optional[str]:
        if not sql_path.exists():
            return None
        try:
            text = sql_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        match = re.search(r"(?im)^\s*create\s+(schema|database)\s+([a-zA-Z0-9_]+)\s*;", text)
        if match:
            return match.group(2)
        match = re.search(r"(?im)^\s*use\s+([a-zA-Z0-9_]+)\s*;", text)
        if match:
            return match.group(1)
        return None

    def _sanitize_mysql_seed_sql(self, project_path: Path, seed_mount: str) -> Optional[str]:
        seed_abs = (project_path / seed_mount.lstrip("./")).resolve()
        if not seed_abs.exists() or not seed_abs.is_file():
            return None
        try:
            text = seed_abs.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        table_names: set[str] = set()
        for m in re.finditer(r"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?`?([a-zA-Z_][a-zA-Z0-9_]*)`?", text):
            table_names.add(m.group(1).strip().lower())

        def _normalize_table_case(line: str) -> str:
            sql_contexts = [
                r"(?i)(create\s+table\s+(?:if\s+not\s+exists\s+)?)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(insert\s+into\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(update\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(delete\s+from\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(from\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(join\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
                r"(?i)(truncate\s+table\s+)`?([a-zA-Z_][a-zA-Z0-9_]*)`?",
            ]
            out = line
            for pattern in sql_contexts:
                def repl(match: re.Match[str]) -> str:
                    prefix = match.group(1)
                    name = match.group(2)
                    lname = name.lower()
                    if not table_names or lname in table_names:
                        return f"{prefix}{lname}"
                    return match.group(0)
                out = re.sub(pattern, repl, out)
            return out

        cleaned_lines: list[str] = []
        for raw in text.splitlines():
            line = _normalize_table_case(raw)
            if re.match(r"(?is)^\s*drop\s+database\b", line):
                continue
            if re.match(r"(?is)^\s*create\s+database\b", line):
                continue
            if re.match(r"(?is)^\s*use\s+\w+\s*;\s*$", line):
                continue
            line = re.sub(r"(?is)\s+engine\s*=\s*myisam", " ENGINE=InnoDB", line)
            cleaned_lines.append(line)

        prelude = [
            "SET NAMES utf8mb4;",
            "SET CHARACTER SET utf8mb4;",
            "SET collation_connection = 'utf8mb4_unicode_ci';",
            "SET FOREIGN_KEY_CHECKS=0;",
        ]
        postlude = ["SET FOREIGN_KEY_CHECKS=1;"]
        sanitized = "\n".join(prelude + [""] + cleaned_lines + [""] + postlude) + "\n"

        out_dir = project_path / ".deploy"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "seed_sanitized.sql"
        if not self._safe_write(out_path, sanitized):
            return None
        return "./.deploy/seed_sanitized.sql"

    def _find_seed_sql_mount(self, project_path: Path, analysis: Optional[ProjectAnalysis] = None) -> Optional[str]:
        candidates: List[Path] = []

        backend_dir = project_path / "backend"
        if backend_dir.exists():
            candidates.extend(sorted(backend_dir.rglob("*.sql")))

        if not candidates:
            candidates.extend(sorted(project_path.rglob("*.sql")))

        if not candidates:
            return self._generate_mysql_seed_from_backend_patterns(project_path, analysis)

        preferred = min(candidates, key=lambda p: (len(p.parts), len(p.name)))
        try:
            rel = preferred.relative_to(project_path).as_posix()
        except Exception:
            return None
        mount = f"./{rel}"
        return self._sanitize_mysql_seed_sql(project_path, mount) or mount

    def _generate_mysql_seed_from_backend_patterns(self, project_path: Path, analysis: Optional[ProjectAnalysis]) -> Optional[str]:
        backend_path = str((analysis.backend_info or {}).get("path") or "backend").strip() if analysis else "backend"
        roots = [project_path / backend_path, project_path]

        insert_patterns: Dict[str, list[str]] = {}
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for ext in ("*.js", "*.ts", "*.mjs", "*.cjs", "*.py"):
                for file_path in root.rglob(ext):
                    if "node_modules" in file_path.parts:
                        continue
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    for m in re.finditer(r"(?i)insert\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^\)]*)\)", text):
                        table = m.group(1).strip().lower()
                        cols_raw = m.group(2)
                        cols = [c.strip().strip("`\"") for c in cols_raw.split(",") if c.strip()]
                        if not cols:
                            continue
                        insert_patterns.setdefault(table, [])
                        for c in cols:
                            if c not in insert_patterns[table]:
                                insert_patterns[table].append(c)

        if not insert_patterns:
            return None

        lines = [
            "SET NAMES utf8mb4;",
            "SET CHARACTER SET utf8mb4;",
            "SET collation_connection = 'utf8mb4_unicode_ci';",
            "SET FOREIGN_KEY_CHECKS=0;",
            "",
        ]

        for table, cols in insert_patterns.items():
            lines.append(f"CREATE TABLE IF NOT EXISTS {table} (")
            lines.append("  id INT AUTO_INCREMENT PRIMARY KEY,")
            for idx, col in enumerate(cols):
                col_l = col.lower()
                if col_l.endswith("id"):
                    col_type = "VARCHAR(64)"
                elif any(token in col_l for token in ("comment", "content", "description", "detail", "body")):
                    col_type = "TEXT"
                else:
                    col_type = "VARCHAR(255)"
                suffix = "," if idx < len(cols) - 1 else ""
                lines.append(f"  {col} {col_type} NULL{suffix}")
            lines.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;")
            lines.append("")

        lines.append("SET FOREIGN_KEY_CHECKS=1;")
        seed = "\n".join(lines) + "\n"

        out_dir = project_path / ".deploy"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "seed_auto.sql"
        if not self._safe_write(out_path, seed):
            return None
        return "./.deploy/seed_auto.sql"

    def _infer_exposed_port(self, dockerfile_content: str, default: int) -> int:
        content = dockerfile_content or ""
        matches = re.findall(r"(?im)^\s*EXPOSE\s+(\d+)", content)
        if not matches:
            return default
        try:
            return int(matches[-1])
        except (TypeError, ValueError):
            return default

    def _harden_nginx_dockerfile(self, dockerfile_content: str) -> str:
        content = (dockerfile_content or "").strip()
        if not content:
            return dockerfile_content

        nginx_listen_port = self._infer_exposed_port(content, 80)

        lowered = content.lower()
        if "from nginx" not in lowered:
            return dockerfile_content

        # If an nginx:alpine image uses curl-based HEALTHCHECK, ensure curl exists.
        if "healthcheck" in lowered and "curl" in lowered:
            if "apk add" not in lowered or "curl" not in lowered:
                # Inject right after the first nginx:alpine FROM.
                content = re.sub(
                    r"(?im)^(FROM\s+nginx:(?:[^\s]*alpine)[^\n]*)(\n)",
                    r"\1\2RUN apk add --no-cache curl\2",
                    content,
                    count=1,
                )

        # Stage-aware hardening for nginx runtime stages.
        # - Some LLM-generated Dockerfiles reference nginx.conf that doesn't exist.
        # - Many set `USER frontend` (or similar) which breaks nginx at runtime.
        lines = content.splitlines()
        hardened_lines: list[str] = []

        in_nginx_stage = False
        nginx_from_index: int | None = None
        removed_missing_nginx_conf = False

        def _maybe_inject_inline_nginx_conf() -> None:
            nonlocal removed_missing_nginx_conf, nginx_from_index
            if not in_nginx_stage or not removed_missing_nginx_conf or nginx_from_index is None:
                return

            insert_at = nginx_from_index + 1
            # Keep curl install (if injected) before writing config.
            while insert_at < len(hardened_lines) and re.match(r"(?im)^\s*RUN\s+apk\s+add\b.*\bcurl\b", hardened_lines[insert_at]):
                insert_at += 1

            # Use a single RUN with printf to avoid relying on Dockerfile heredoc support.
            inline_conf = [
                "RUN printf '%s\\n' \\",
                "  'server {' \\",
                f"  '  listen {int(nginx_listen_port)};' \\",
                "  '  server_name _;' \\",
                "  '  root /usr/share/nginx/html;' \\",
                "  '  index index.html;' \\",
                "  '  location / {' \\",
                "  '    try_files $uri $uri/ /index.html;' \\",
                "  '  }' \\",
                "  '}' \\",
                "  > /etc/nginx/conf.d/default.conf",
            ]

            # Avoid duplicate injection.
            if not any("/etc/nginx/conf.d/default.conf" in l and "try_files $uri" in l for l in hardened_lines):
                hardened_lines[insert_at:insert_at] = inline_conf

            removed_missing_nginx_conf = False
            nginx_from_index = None

        for line in lines:
            from_match = re.match(r"(?im)^\s*FROM\s+([^\s]+)", line)
            if from_match:
                # Finalize the previous stage before switching.
                _maybe_inject_inline_nginx_conf()

                base = from_match.group(1).lower()
                in_nginx_stage = "nginx" in base
                if in_nginx_stage:
                    nginx_from_index = len(hardened_lines)
                    removed_missing_nginx_conf = False

            if in_nginx_stage:
                # Drop missing nginx.conf copies; we'll replace with a safe inline config.
                if re.match(
                    r"(?im)^\s*COPY\s+[^\s]*nginx\.conf\s+/etc/nginx/conf\.d/default\.conf\s*$",
                    line,
                ):
                    removed_missing_nginx_conf = True
                    continue
                if re.match(
                    r"(?im)^\s*COPY\s+[^\s]*nginx\.conf\s+/etc/nginx/nginx\.conf\s*$",
                    line,
                ):
                    removed_missing_nginx_conf = True
                    continue

                # Prefer root for nginx stage for compatibility (bind 80, writable dirs).
                if re.match(r"(?im)^\s*USER\s+", line):
                    continue

                # nginx:alpine already provides an nginx user/group. Re-creating it is a
                # common LLM mistake and fails deterministically with "user 'nginx' in use".
                if re.match(r"(?im)^\s*RUN\s+.*\badduser\b.*\bnginx\b", line):
                    continue
                if re.match(r"(?im)^\s*RUN\s+.*\baddgroup\b.*\bnginx\b", line):
                    continue
                if re.match(r"(?im)^\s*RUN\s+.*\b(addgroup|groupadd)\b.*\bnodejs\b.*\b(adduser|useradd)\b.*\bnginx\b", line):
                    continue
                if re.match(r"(?im)^\s*RUN\s+.*\b(adduser|useradd)\b.*\bnginx\b.*\b(addgroup|groupadd)\b.*\bnodejs\b", line):
                    continue

            hardened_lines.append(line)

        # Finalize last stage.
        _maybe_inject_inline_nginx_conf()

        content = "\n".join(hardened_lines)

        # Remove previously injected pid override command (causes duplicate pid directive
        # for some nginx images/configs).
        content = content.replace(
            'CMD ["nginx", "-g", "daemon off; pid /tmp/nginx.pid;"]\n',
            'CMD ["nginx", "-g", "daemon off;"]\n',
        ).replace(
            'CMD ["nginx", "-g", "daemon off; pid /tmp/nginx.pid;"]',
            'CMD ["nginx", "-g", "daemon off;"]',
        )

        # If container runs as nginx user, ensure required runtime dirs are writable.
        if "user nginx" in content.lower():
            lines = content.splitlines()
            insert_at = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("user nginx")), len(lines))
            permission_line = (
                "RUN mkdir -p /var/cache/nginx/client_temp /run && "
                "chown -R nginx:nginx /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /usr/share/nginx/html /run"
            )
            if "/var/cache/nginx" not in content:
                lines.insert(insert_at, permission_line)
                insert_at += 1
            if "/run/nginx.pid" not in content and "/var/run/nginx.pid" not in content:
                lines.insert(insert_at, "RUN touch /run/nginx.pid && chown nginx:nginx /run/nginx.pid")
            content = "\n".join(lines)

        if not content.endswith("\n"):
            content += "\n"
        return content

    def _inject_frontend_artifact_aliases(self, dockerfile_content: str) -> str:
        """Bridge common frontend build outputs (dist/build/out) deterministically.

        Keeps LLM-generated Dockerfiles mostly intact while hardening for frequent
        Next/Vite/CRA output-path mismatches in multi-stage nginx images.
        """
        content = dockerfile_content or ""
        if not content:
            return dockerfile_content
        if "deployer-artifact-alias" in content:
            return dockerfile_content
        if "npm run build" not in content.lower():
            return dockerfile_content

        lines = content.splitlines()
        build_idx = None
        for i, line in enumerate(lines):
            if re.match(r"(?im)^\s*RUN\s+npm\s+run\s+build\b", line):
                build_idx = i
                break
        if build_idx is None:
            return dockerfile_content

        alias_block = [
            "# deployer-artifact-alias: keep dist/build/out in sync", 
            "RUN set -eux; \\",
            "  for src in dist build out; do \\",
            "    if [ -d \"/app/$src\" ]; then \\",
            "      for dst in dist build out; do \\",
            "        if [ \"$src\" != \"$dst\" ] && [ ! -d \"/app/$dst\" ]; then mkdir -p \"/app/$dst\" && cp -a \"/app/$src/.\" \"/app/$dst/\" || true; fi; \\",
            "      done; \\",
            "      break; \\",
            "    fi; \\",
            "  done",
        ]
        lines[build_idx + 1:build_idx + 1] = alias_block
        out = "\n".join(lines)
        if dockerfile_content.endswith("\n"):
            out += "\n"
        return out

    def _apply_deterministic_repair_policy(self, dockerfile_content: str, error: str, service_name: str) -> str:
        """Deterministic guard rails used *after* LLM-first repair attempts."""
        content = dockerfile_content or ""
        if service_name != "frontend":
            return content

        lowered_err = (error or "").lower()
        if any(p in lowered_err for p in ["copy failed: stat app/out", "copy failed: stat app/dist", "copy failed: stat app/build"]):
            return self._inject_frontend_artifact_aliases(content)
        return self._inject_frontend_artifact_aliases(content)

    async def build_deployment_config(
        self,
        project_id: str,
        project_path: Path,
        analysis: ProjectAnalysis,
        *,
        deploy_mode: str | None = None,
    ) -> DeploymentConfig:
        """Generate build spec + Dockerfiles based on deploy mode."""
        context_root = project_path
        if analysis:
            if (deploy_mode or analysis.project_type) == "backend-only":
                backend_path = (analysis.backend_info or {}).get("path")
                if backend_path:
                    candidate = project_path / backend_path
                    if candidate.exists():
                        context_root = candidate
            elif (deploy_mode or analysis.project_type) == "frontend-only":
                frontend_path = (analysis.frontend_info or {}).get("path")
                if frontend_path:
                    candidate = project_path / frontend_path
                    if candidate.exists():
                        context_root = candidate

        file_tree = build_file_tree(context_root)
        file_samples = sample_key_files(context_root)

        # Determine deploy mode
        mode = deploy_mode or analysis.project_type
        if mode in ("static-html",):
            mode = "frontend-only"

        # Auto-adapt project files in a non-manual way before LLM/build steps.
        self._auto_adapt_project_files(project_path, analysis, mode or "auto")

        detected_db_info = self._detect_database_info(project_path, analysis)

        # 1. Build spec
        logger.info("Generating build spec for %s (mode=%s)", project_id, mode)
        build_spec = await docker_generator.generate_build_spec(analysis, file_tree, file_samples)
        if mode in ("frontend-only", "backend-only"):
            build_spec = self._apply_deploy_mode_to_build_spec(build_spec, mode)

        # 2. Generate Dockerfiles based on mode
        dockerfiles: Dict[str, str] = {}
        ports: Dict[str, int] = {}

        if mode == "frontend-only":
            dockerfiles, ports = await self._gen_frontend_only(analysis, build_spec, file_samples, project_path)

        elif mode == "backend-only":
            dockerfiles, ports = await self._gen_backend_only(analysis, build_spec, file_samples, project_path)

        elif mode == "fullstack":
            dockerfiles, ports = await self._gen_fullstack(analysis, build_spec, file_samples, project_path)

        else:
            # Fallback: single Dockerfile
            dockerfile = await docker_generator.generate_dockerfile(
                analysis, build_spec, file_samples, deploy_mode=mode,
            )
            dockerfiles = {"app": dockerfile}
            ports = analysis.recommended_ports or {"app": 8000}

        if not ports:
            ports = {"app": 8000}

        environment: Dict[str, str] = {}

        if mode != "frontend-only":
            # Inject required runtime secrets.
            # Some apps (e.g. jsonwebtoken) crash at runtime if JWT_SECRET is missing.
            # We keep this deterministic per project so redeploys stay stable.
            try:
                if "JWT_SECRET" not in environment:
                    backend_info = analysis.backend_info or {}
                    backend_path = str(backend_info.get("path") or "").strip()

                    jwt_needed = False

                    # Heuristic 1: sampled files reference JWT_SECRET.
                    for sample in (file_samples or {}).values():
                        if not isinstance(sample, str):
                            continue
                        if "process.env.JWT_SECRET" in sample or "JWT_SECRET" in sample:
                            jwt_needed = True
                            break

                    # Heuristic 2: search common backend locations for .env.example.
                    if not jwt_needed:
                        candidates: List[Path] = []
                        if backend_path:
                            candidates.append(project_path / backend_path)
                        for rel in ("backend", "server", "api"):
                            p = project_path / rel
                            if p.exists() and p.is_dir():
                                candidates.append(p)
                        candidates.append(project_path)

                        seen: set[str] = set()
                        for base in candidates:
                            key = str(base.resolve())
                            if key in seen:
                                continue
                            seen.add(key)
                            env_example = base / ".env.example"
                            if not env_example.exists():
                                continue
                            text = env_example.read_text(encoding="utf-8", errors="replace")
                            if "JWT_SECRET" in text:
                                jwt_needed = True
                                break

                    if jwt_needed:
                        derived = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:32]
                        environment["JWT_SECRET"] = derived
            except Exception:
                pass

        # Seed DB env vars if we detect a DB, even if analysis missed it.
        if mode != "frontend-only" and detected_db_info and detected_db_info.get("detected"):
            db_type = str(detected_db_info.get("type") or "").lower() or "postgres"
            if db_type in {"mysql", "mariadb"}:
                seed_path = self._find_seed_sql_mount(project_path, analysis)
                schema = None
                if seed_path:
                    seed_abs = (project_path / seed_path.lstrip("./")).resolve()
                    schema = self._extract_sql_schema_name(seed_abs)
                db_name = schema or "app_db"
                db_user = "app"
                db_password = "app_secret"
                environment.update(
                    {
                        "DB_HOST": "db",
                        "DB_NAME": db_name,
                        "DB_USER": db_user,
                        "DB_USERNAME": db_user,
                        "DB_PASS": db_password,
                        "DB_PASSWORD": db_password,
                        "DB_PORT": "3306",
                        # Also set mysql env for db container overrides.
                        "MYSQL_HOST": "db",
                        "MYSQL_PORT": "3306",
                        "MYSQL_DATABASE": db_name,
                        "MYSQL_USER": db_user,
                        "MYSQL_PASSWORD": db_password,
                        "MYSQL_ROOT_PASSWORD": "root_secret",
                        "MYSQL_DB": db_name,
                        "DATABASE_URL": f"mysql://{db_user}:{db_password}@db:3306/{db_name}",
                    }
                )

        if mode != "frontend-only":
            has_db_credentials = any(
                str(environment.get(k) or "").strip()
                for k in ("DB_PASSWORD", "DB_PASS", "MYSQL_PASSWORD", "DB_NAME", "MYSQL_DATABASE")
            )
            db_password = str(
                environment.get("DB_PASSWORD")
                or environment.get("DB_PASS")
                or environment.get("MYSQL_PASSWORD")
                or ""
            ).strip()
            db_user = str(
                environment.get("DB_USER")
                or environment.get("DB_USERNAME")
                or environment.get("MYSQL_USER")
                or ""
            ).strip()
            db_name = str(
                environment.get("DB_NAME")
                or environment.get("MYSQL_DATABASE")
                or environment.get("MYSQL_DB")
                or ""
            ).strip()
            db_host = str(
                environment.get("DB_HOST")
                or environment.get("MYSQL_HOST")
                or ""
            ).strip()

            if db_password:
                environment["DB_PASSWORD"] = db_password
                environment["DB_PASS"] = db_password
                environment["MYSQL_PASSWORD"] = db_password
            if db_user:
                environment["DB_USER"] = db_user
                environment["DB_USERNAME"] = db_user
                environment["MYSQL_USER"] = db_user
            if db_name:
                environment["DB_NAME"] = db_name
                environment["MYSQL_DATABASE"] = db_name
                environment["MYSQL_DB"] = db_name
            if db_host:
                environment["DB_HOST"] = db_host
                environment["MYSQL_HOST"] = db_host
            if has_db_credentials:
                environment["DB_HOST"] = "db"
                environment["MYSQL_HOST"] = "db"
                environment["DB_PORT"] = "3306"
                environment["MYSQL_PORT"] = "3306"

        if mode != "frontend-only":
            # Generate a portable .env.deployer early (before compose run) so bundles
            # and local runs have consistent env. We base it on env_generator output
            # but override keys with the actual runtime environment we inject.
            try:
                from app.deployment.services.docker.env_generator import find_existing_env, generate_env_with_llm

                env_path = project_path / ".env.deployer"
                if env_path.exists() and env_path.is_dir():
                    shutil.rmtree(env_path, ignore_errors=True)
                    env_path.write_text("", encoding="utf-8")
                if env_path.exists() and env_path.stat().st_size > 0:
                    env_content = env_path.read_text(encoding="utf-8", errors="replace")
                else:
                    env_content = await generate_env_with_llm(
                        project_path,
                        analysis,
                        json.dumps(file_tree, ensure_ascii=False),
                        json.dumps(file_samples, ensure_ascii=False),
                    )

                env_content = self._apply_env_overrides(env_content, environment)
                env_path.write_text(env_content, encoding="utf-8")
            except Exception:
                # Ensure the file exists so compose mounts won't fail.
                try:
                    env_path = project_path / ".env.deployer"
                    if env_path.exists() and env_path.is_dir():
                        shutil.rmtree(env_path, ignore_errors=True)
                    if not env_path.exists():
                        env_path.write_text("", encoding="utf-8")
                except Exception:
                    pass

        return DeploymentConfig(
            deployment_id=project_id,
            project_id=project_id,
            dockerfile_content=dockerfiles.get("backend") or dockerfiles.get("frontend") or dockerfiles.get("app", ""),
            build_context=str(project_path),
            ports=ports,
            environment=environment,
            build_spec={
                **build_spec,
                "deploy_mode": mode,
                "dockerfiles": {k: f"Dockerfile.{k}" for k in dockerfiles},
                "_dockerfile_contents": dockerfiles,
                "_db_info": detected_db_info,
            },
        )

    def _apply_deploy_mode_to_build_spec(
        self,
        build_spec: Dict[str, Any],
        mode: str,
    ) -> Dict[str, Any]:
        if mode not in {"frontend-only", "backend-only"}:
            return build_spec
        if not isinstance(build_spec, dict):
            return build_spec
        modules = build_spec.get("modules")
        if not isinstance(modules, list) or not modules:
            return build_spec

        def _is_frontend(module: Dict[str, Any]) -> bool:
            if module.get("type") == "frontend":
                return True
            framework = str(module.get("framework") or "").lower()
            if framework in {"react", "vue", "angular", "svelte", "nextjs", "nuxt", "astro", "remix", "sveltekit"}:
                return True
            path = str(module.get("path") or "").lower()
            return any(token in path for token in ("frontend", "client", "web", "ui"))

        def _is_backend(module: Dict[str, Any]) -> bool:
            if module.get("type") == "backend":
                return True
            framework = str(module.get("framework") or "").lower()
            if framework in {"spring", "express", "koa", "fastify", "nestjs", "django", "flask", "fastapi", "gin", "fiber"}:
                return True
            language = str(module.get("language") or "").lower()
            if language in {"python", "java", "go", "csharp", "ruby", "php"}:
                return True
            path = str(module.get("path") or "").lower()
            return any(token in path for token in ("backend", "server", "api"))

        def _score_frontend(module: Dict[str, Any]) -> int:
            score = 0
            if module.get("type") == "frontend":
                score += 100
            framework = str(module.get("framework") or "").lower()
            language = str(module.get("language") or "").lower()
            path = str(module.get("path") or "").lower()
            if framework in {"react", "vue", "angular", "svelte", "nextjs", "nuxt", "astro", "remix", "sveltekit"}:
                score += 50
            if language in {"javascript", "typescript", "html"}:
                score += 20
            if any(token in path for token in ("frontend", "client", "web", "ui")):
                score += 10
            if any(token in path for token in ("backend", "server", "api")):
                score -= 30
            return score

        def _score_backend(module: Dict[str, Any]) -> int:
            score = 0
            if module.get("type") == "backend":
                score += 100
            framework = str(module.get("framework") or "").lower()
            language = str(module.get("language") or "").lower()
            path = str(module.get("path") or "").lower()
            if framework in {"spring", "express", "koa", "fastify", "nestjs", "django", "flask", "fastapi", "gin", "fiber"}:
                score += 50
            if language in {"python", "java", "go", "csharp", "ruby", "php"}:
                score += 20
            if any(token in path for token in ("backend", "server", "api")):
                score += 10
            if any(token in path for token in ("frontend", "client", "web", "ui")):
                score -= 30
            return score

        if mode == "frontend-only":
            filtered = [m for m in modules if isinstance(m, dict) and _is_frontend(m)]
            if not filtered:
                candidates = [m for m in modules if isinstance(m, dict)]
                if candidates:
                    filtered = [max(candidates, key=_score_frontend)]
            build_spec["modules"] = filtered or modules
        else:
            filtered = [m for m in modules if isinstance(m, dict) and _is_backend(m)]
            if not filtered:
                candidates = [m for m in modules if isinstance(m, dict)]
                if candidates:
                    filtered = [max(candidates, key=_score_backend)]
            build_spec["modules"] = filtered or modules

        return build_spec

    # ── Mode: frontend-only (1 service) ──────────────────────────

    async def _gen_frontend_only(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
        project_path: Path,
    ) -> tuple[Dict[str, str], Dict[str, int]]:
        logger.info("Mode: frontend-only → 1 service")
        fe = analysis.frontend_info or {}
        frontend_path, frontend_root = self._resolve_frontend_root(analysis, build_spec, project_path)
        default_port = int(fe.get("port", 3000) or 3000)
        if self._is_static_frontend(frontend_root):
            dockerfile = self._render_static_frontend_dockerfile(frontend_path if frontend_path != "." else ".")
            return {"frontend": dockerfile}, {"frontend": 80}
        if self._frontend_uses_buildless_runtime(frontend_root):
            dockerfile = self._render_node_static_frontend_dockerfile(frontend_path if frontend_path != "." else ".", default_port)
            return {"frontend": dockerfile}, {"frontend": default_port}

        dockerfile = await docker_generator.generate_frontend_dockerfile(analysis, build_spec, file_samples)
        port = self._infer_exposed_port(dockerfile, default_port)
        return {"frontend": dockerfile}, {"frontend": port}

    # ── Mode: backend-only (1-2 services) ────────────────────────

    async def _gen_backend_only(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
        project_path: Path,
    ) -> tuple[Dict[str, str], Dict[str, int]]:
        has_db = bool(analysis.database_info and analysis.database_info.get("detected"))
        logger.info("Mode: backend-only → %s", "2 services (backend+DB)" if has_db else "1 service")
        dockerfile = await docker_generator.generate_backend_dockerfile(analysis, build_spec, file_samples)
        backend_root = project_path
        backend_path = (analysis.backend_info or {}).get("path")
        if backend_path:
            candidate = project_path / backend_path
            if candidate.exists():
                backend_root = candidate
        be = analysis.backend_info or {}
        port = be.get("port", 8000) or 8000
        dockerfile = self._normalize_node_backend_cmd(dockerfile, backend_root, container_port=port)
        dockerfile = self._apply_healthcheck_policy(dockerfile, port)
        return {"backend": dockerfile}, {"backend": port}

    # ── Mode: fullstack (2-3 services) ───────────────────────────

    async def _gen_fullstack(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
        project_path: Path,
    ) -> tuple[Dict[str, str], Dict[str, int]]:
        has_db = bool(analysis.database_info and analysis.database_info.get("detected"))
        n_services = 3 if has_db else 2
        logger.info("Mode: fullstack → %d services", n_services)

        fe = analysis.frontend_info or {}
        frontend_path, frontend_root = self._resolve_frontend_root(analysis, build_spec, project_path)
        frontend_default_port = int(fe.get("port", 3000) or 3000)
        if frontend_root.exists() and self._is_static_frontend(frontend_root):
            frontend_df = self._render_static_frontend_dockerfile(frontend_path if frontend_path != "." else ".")
        elif self._frontend_uses_buildless_runtime(frontend_root):
            frontend_df = self._render_node_static_frontend_dockerfile(frontend_path if frontend_path != "." else ".", frontend_default_port)
        else:
            frontend_df = await docker_generator.generate_frontend_dockerfile(analysis, build_spec, file_samples)

        backend_df = await docker_generator.generate_backend_dockerfile(analysis, build_spec, file_samples)
        backend_root = project_path / "backend"
        backend_path = (analysis.backend_info or {}).get("path")
        if backend_path:
            candidate = project_path / backend_path
            if candidate.exists():
                backend_root = candidate
        be = analysis.backend_info or {}
        backend_port = be.get("port", 8000) or 8000
        backend_df = self._normalize_node_backend_cmd(backend_df, backend_root, container_port=backend_port)
        backend_df = self._apply_healthcheck_policy(backend_df, backend_port)

        frontend_port = self._infer_exposed_port(frontend_df, frontend_default_port)
        ports = {
            "frontend": frontend_port,
            "backend": backend_port,
        }
        return {"frontend": frontend_df, "backend": backend_df}, ports

    # ── Build and Run ────────────────────────────────────────────

    async def build_and_run(
        self,
        config: DeploymentConfig,
        project_path: Path,
        analysis: ProjectAnalysis,
    ) -> Dict[str, Any]:
        """Write Dockerfiles, build images, run containers.

        Handles single-container and multi-service (compose) modes.
        Saves images as .tar.gz after successful build.
        """
        build_spec = config.build_spec or {}
        deploy_mode = build_spec.get("deploy_mode", analysis.project_type)
        dockerfile_contents = build_spec.get("_dockerfile_contents", {})
        file_samples = sample_key_files(project_path)

        db_info = (build_spec.get("_db_info") or analysis.database_info or {}) if analysis else (build_spec.get("_db_info") or {})
        has_db = bool(db_info and db_info.get("detected"))

        # Determine if we need compose (multi-service)
        needs_compose = (
            deploy_mode == "fullstack"
            or (deploy_mode == "backend-only" and has_db)
        )

        # Write Dockerfiles
        image_tags: Dict[str, str] = {}
        hardened_contents: Dict[str, str] = {}
        frontend_rel, frontend_root = self._resolve_frontend_root(analysis, build_spec, project_path)
        nextjs_ssr_frontend = self._is_nextjs_ssr_frontend(frontend_root)
        backend_root = project_path
        backend_path = (analysis.backend_info or {}).get("path") if analysis else None
        if backend_path:
            candidate = project_path / backend_path
            if candidate.exists():
                backend_root = candidate

        for service_name, content in dockerfile_contents.items():
            if service_name == "backend":
                be_port = None
                if analysis:
                    be_port = (analysis.backend_info or {}).get("port", 8000) or 8000
                content = self._normalize_node_backend_cmd(content, backend_root, container_port=be_port)
                content = self._apply_healthcheck_policy(content, be_port)
                content = self._harden_backend_dockerfile(content)
                content = self._ensure_runtime_dotenv_file(content)
            if service_name == "frontend":
                if nextjs_ssr_frontend:
                    frontend_port = int((analysis.frontend_info or {}).get("port") or 3000) if analysis else 3000
                    logger.info("Using deterministic Next.js runtime frontend Dockerfile (LLM-first guard rail)")
                    content = self._render_nextjs_runtime_frontend_dockerfile(frontend_rel, frontend_port)
                content = self._inject_nginx_extra_assets(content, project_path)
                content = self._inject_frontend_artifact_aliases(content)
            hardened = self._harden_nginx_dockerfile(content)
            hardened_contents[service_name] = hardened
            if needs_compose:
                df_path = project_path / f"Dockerfile.{service_name}"
            else:
                df_path = project_path / "Dockerfile"
            df_path.write_text(hardened, encoding="utf-8")

        # Re-sync config.ports with the actual EXPOSE directives from the hardened
        # Dockerfiles.  _harden_nginx_dockerfile() can change EXPOSE (e.g. 8080→80)
        # *after* the initial port was stored in config.ports, so we must update here
        # before compose is generated to avoid a host→wrong-container-port mismatch.
        for service_name, hardened_df in hardened_contents.items():
            if service_name in config.ports:
                config.ports[service_name] = self._infer_exposed_port(
                    hardened_df, config.ports[service_name]
                )

        # Build images with repair loop
        all_build_logs: list[str] = []
        for service_name, content in hardened_contents.items():
            tag = f"deployer-{config.project_id}-{service_name}:latest"
            df_name = f"Dockerfile.{service_name}" if needs_compose else "Dockerfile"

            built_tag, svc_logs = await self._build_with_repair(
                project_path, tag, df_name, content, service_name, build_spec, file_samples,
            )
            image_tags[service_name] = built_tag
            all_build_logs.append(f"=== {service_name} ===\n{svc_logs}")

        build_logs_text = "\n\n".join(all_build_logs)

        # Save images as .tar.gz for portability
        saved_images = await self._save_images(config.project_id, image_tags)

        # Run
        if needs_compose:
            result = await self._run_compose(
                config, project_path, analysis, image_tags, deploy_mode,
            )
        else:
            # Single service
            service_name = list(image_tags.keys())[0]
            tag = image_tags[service_name]
            result = self._run_single(config, tag, service_name, saved_images)

        result["build_logs"] = build_logs_text
        return result

    async def _build_with_repair(
        self,
        project_path: Path,
        tag: str,
        dockerfile_name: str,
        dockerfile_content: str,
        service_name: str,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
    ) -> tuple[str, str]:
        """Build an image with LLM-powered repair loop.

        Returns ``(tag, build_log_text)``.
        """
        max_repairs = settings.max_repair_attempts
        build_timeout = float(getattr(settings, "docker_build_timeout_seconds", 1200) or 1200)
        current_content = dockerfile_content
        last_error = ""
        all_logs: list[str] = []

        if service_name == "backend":
            current_content = self._harden_backend_dockerfile(current_content)
        if service_name == "frontend":
            current_content = self._inject_frontend_artifact_aliases(current_content)
        current_content = self._harden_nginx_dockerfile(current_content)
        (project_path / dockerfile_name).write_text(current_content, encoding="utf-8")

        for attempt in range(max_repairs + 1):
            log_collector: list[str] = []
            try:
                if attempt > 0:
                    logger.info("Repair attempt %d/%d for %s", attempt, max_repairs, dockerfile_name)
                    prev_content = current_content
                    repair_exc: DockerError | None = None
                    try:
                        current_content = await docker_generator.repair_dockerfile(
                            current_content, last_error, build_spec, file_samples,
                        )
                    except DockerError as exc:
                        repair_exc = exc
                        logger.warning("LLM repair failed for %s: %s", dockerfile_name, exc)

                    current_content = self._apply_deterministic_repair_policy(
                        current_content, last_error, service_name,
                    )
                    if repair_exc and current_content == prev_content:
                        raise repair_exc

                    if service_name == "backend":
                        current_content = self._harden_backend_dockerfile(current_content)
                    if service_name == "frontend":
                        current_content = self._inject_frontend_artifact_aliases(current_content)
                    current_content = self._harden_nginx_dockerfile(current_content)
                    (project_path / dockerfile_name).write_text(current_content, encoding="utf-8")

                await asyncio.wait_for(
                    asyncio.to_thread(
                        docker_client.build_image,
                        str(project_path),
                        tag,
                        dockerfile=dockerfile_name,
                        log_collector=log_collector,
                    ),
                    timeout=build_timeout,
                )
                all_logs.extend(log_collector)
                return tag, "\n".join(all_logs)
            except asyncio.TimeoutError as exc:
                all_logs.extend(log_collector)
                last_error = f"Docker build timed out after {int(build_timeout)}s"
                logger.warning("Build timeout (%s attempt %d): %s", dockerfile_name, attempt + 1, last_error)
                if attempt >= max_repairs:
                    raise DockerError(
                        f"Build of {dockerfile_name} timed out after {int(build_timeout)}s and {max_repairs} repair attempts"
                    ) from exc

            except DockerError as exc:
                all_logs.extend(log_collector)
                last_error = str(exc)
                logger.warning("Build failed (%s attempt %d): %s", dockerfile_name, attempt + 1, last_error[:200])
                if attempt >= max_repairs:
                    raise DockerError(
                        f"Build of {dockerfile_name} failed after {max_repairs} repair attempts: {last_error}"
                    ) from exc

        return tag, "\n".join(all_logs)  # unreachable

    async def _save_images(self, project_id: str, image_tags: Dict[str, str]) -> Dict[str, str]:
        """Save built images as .tar.gz for portability and restore."""
        saved: Dict[str, str] = {}
        images_dir = Path(settings.projects_dir) / project_id / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        for service, tag in image_tags.items():
            tar_path = images_dir / f"{service}.tar.gz"
            try:
                docker_client.save_image(tag, str(tar_path))
                saved[service] = str(tar_path)
                logger.info("Saved image %s → %s", tag, tar_path)
            except Exception as exc:
                logger.warning("Failed to save image %s: %s", tag, exc)

        return saved

    def _run_single(
        self,
        config: DeploymentConfig,
        tag: str,
        service_name: str,
        saved_images: Dict[str, str],
    ) -> Dict[str, Any]:
        """Run a single container with dynamic host port."""
        result = docker_client.run_container(
            tag,
            name=config.project_id,
            ports=config.ports,
            environment=config.environment,
        )

        ports = result.get("ports", [])
        preview_port = ports[0]["hostPort"] if ports else None

        # Build service_ports list for proxy routing
        service_ports = []
        for p in ports:
            service_ports.append({
                "service": service_name,
                "container_port": p["containerPort"],
                "host_port": p["hostPort"],
                "url": f"http://localhost:{p['hostPort']}",
            })

        return {
            "container_id": result["container_id"],
            "image_tag": tag,
            "image_tags": {service_name: tag},
            "ports": ports,
            "service_ports": service_ports,
            "preview_url": f"http://localhost:{preview_port}" if preview_port else None,
            "saved_images": saved_images,
        }

    async def _run_compose(
        self,
        config: DeploymentConfig,
        project_path: Path,
        analysis: ProjectAnalysis,
        image_tags: Dict[str, str],
        deploy_mode: str,
    ) -> Dict[str, Any]:
        """Generate compose file with dynamic host ports and run."""
        build_spec = config.build_spec or {}
        db_info = build_spec.get("_db_info") or (analysis.database_info or {})
        has_db = db_info.get("detected", False)
        db_type = db_info.get("type") if has_db else None

        backend_tag = image_tags.get("backend")
        frontend_tag = image_tags.get("frontend")
        backend_port = config.ports.get("backend", 8000)
        frontend_port = config.ports.get("frontend", 3000)
        db_seed_mount = self._find_seed_sql_mount(project_path, analysis) if db_type in {"mysql", "mariadb"} else None
        if db_seed_mount and db_type in {"mysql", "mariadb"}:
            db_seed_mount = self._prepare_mysql_seed_sql(project_path, db_seed_mount)

        # generate_compose_yaml now returns (yaml, port_map)
        compose_content, port_map = generate_compose_yaml(
            project_name=config.project_id,
            backend_image=backend_tag,
            backend_port=backend_port,
            frontend_image=frontend_tag if deploy_mode == "fullstack" else None,
            frontend_port=frontend_port,
            database_type=db_type,
            db_init_sql=db_seed_mount,
            db_ephemeral=settings.db_ephemeral_default,
            db_tmpfs_size=settings.db_tmpfs_size,
            environment=config.environment,
        )

        compose_path = project_path / "docker-compose.yml"
        compose_path.write_text(compose_content, encoding="utf-8")

        project_name = config.project_id
        docker_client.compose_up(str(project_path), project_name)

        services = list(image_tags.keys())
        if db_type:
            services.append("db")

        # Build service_ports from port_map for proxy routing
        service_ports = []
        for svc, pm in port_map.items():
            service_ports.append({
                "service": svc,
                "container_port": pm["container"],
                "host_port": pm["host"],
                "url": f"http://localhost:{pm['host']}",
            })

        # Primary URL = frontend if available, else backend
        primary_port = port_map.get("frontend", port_map.get("backend", {}))
        primary_url = f"http://localhost:{primary_port.get('host', 8000)}" if primary_port else None

        return {
            "container_id": None,
            "compose_project": project_name,
            "compose_file": str(compose_path),
            "compose_services": services,
            "image_tag": backend_tag or frontend_tag,
            "image_tags": image_tags,
            "ports": [],
            "service_ports": service_ports,
            "preview_url": primary_url,
            "saved_images": {},
        }


# Singleton
docker_builder = DockerBuilder()
