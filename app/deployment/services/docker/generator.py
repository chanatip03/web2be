"""LLM-based Dockerfile generation — mode-aware (frontend-only, backend-only, fullstack split).

Generates separate Dockerfiles per service when needed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings
from app.deployment.core.exceptions import DockerError
from app.deployment.models.project import ProjectAnalysis
from app.deployment.services.analyzer.file_scanner import build_file_tree, sample_key_files
from app.deployment.services.llm.client import llm_client
from app.deployment.services.llm.parser import extract_json, extract_text_content
from app.deployment.services.llm.prompts import (
    BUILD_SPEC_SYSTEM,
    BUILD_SPEC_USER,
    DOCKERFILE_SYSTEM,
    DOCKERFILE_USER,
    DOCKERFILE_FRONTEND_SYSTEM,
    DOCKERFILE_FRONTEND_USER,
    DOCKERFILE_BACKEND_SYSTEM,
    DOCKERFILE_BACKEND_USER,
    REPAIR_SYSTEM,
    REPAIR_USER,
)

logger = logging.getLogger(__name__)


class DockerGenerator:
    """Generate Dockerfiles and build-specs using LLM — mode-aware."""

    async def _collect_llm_advisory(self, system_prompt: str, user_prompt: str, step: str) -> None:
        if not settings.llm_advisory_only:
            return
        try:
            advice = await llm_client.generate(system_prompt, user_prompt)
            logger.info("LLM advisory (%s): %s", step, (advice or "")[:400])
        except Exception as exc:
            logger.info("LLM advisory unavailable (%s): %s", step, exc)

    def _fallback_node_backend_dockerfile(self, analysis: ProjectAnalysis) -> str:
        be = analysis.backend_info or {}
        backend_path = be.get("path") or "backend"
        port = be.get("port", 8000) or 8000

        # Keep this intentionally minimal; DockerBuilder will normalize CMD and harden when needed.
        lines = [
            "FROM node:20-alpine",
            "WORKDIR /app",
            "RUN apk add --no-cache curl",
            f"COPY {backend_path}/package*.json ./",
            "RUN npm ci",
            f"COPY {backend_path}/ ./",
            f"EXPOSE {int(port)}",
            "HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \\",
            f"  CMD curl -f http://localhost:{int(port)}/ || exit 1",
            "CMD [\"npm\", \"start\"]",
        ]
        return "\n".join(lines) + "\n"

    # ── Build Spec ───────────────────────────────────────────────

    async def generate_build_spec(
        self,
        analysis: ProjectAnalysis,
        file_tree: Dict[str, Any],
        file_samples: Dict[str, str],
    ) -> Dict[str, Any]:
        """Ask LLM for a build specification."""
        analysis_str = analysis.model_dump_json(indent=2)
        tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        samples_str = _format_samples(file_samples)

        user_prompt = BUILD_SPEC_USER.format(
            analysis=analysis_str,
            file_tree=tree_str,
            file_samples=samples_str,
        )

        if settings.llm_advisory_only:
            await self._collect_llm_advisory(BUILD_SPEC_SYSTEM, user_prompt, "build_spec")
            return self._default_build_spec(analysis)

        result = await llm_client.analyze_json(BUILD_SPEC_SYSTEM, user_prompt)

        if not result:
            raise DockerError("LLM failed to generate a build spec — no fallback (LLM-only mode)")

        return result

    # ── Generic (single) Dockerfile ──────────────────────────────

    async def generate_dockerfile(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
        *,
        deploy_mode: str = "auto",
    ) -> str:
        """Generate a single Dockerfile (used for frontend-only or backend-only single-service)."""
        analysis_str = analysis.model_dump_json(indent=2)
        spec_str = json.dumps(build_spec, indent=2, ensure_ascii=False)
        samples_str = _format_samples(file_samples)

        user_prompt = DOCKERFILE_USER.format(
            project_type=analysis.project_type,
            deploy_mode=deploy_mode,
            analysis=analysis_str,
            build_spec=spec_str,
            file_samples=samples_str,
        )

        if settings.llm_advisory_only:
            await self._collect_llm_advisory(DOCKERFILE_SYSTEM, user_prompt, "dockerfile_generic")
            if analysis.project_type == "frontend-only":
                return self._deterministic_frontend_dockerfile(analysis)
            return self._deterministic_backend_dockerfile(analysis)

        raw = await llm_client.generate(DOCKERFILE_SYSTEM, user_prompt)
        dockerfile = extract_text_content(raw)

        if not dockerfile or "FROM" not in dockerfile.upper():
            raise DockerError("LLM failed to generate a valid Dockerfile")

        return dockerfile

    # ── Frontend Dockerfile ──────────────────────────────────────

    async def generate_frontend_dockerfile(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
    ) -> str:
        """Generate a Dockerfile specifically for the FRONTEND."""
        fe_info = json.dumps(analysis.frontend_info or {}, indent=2, ensure_ascii=False)
        spec_str = json.dumps(build_spec, indent=2, ensure_ascii=False)
        samples_str = _format_samples(file_samples)

        user_prompt = DOCKERFILE_FRONTEND_USER.format(
            frontend_info=fe_info,
            build_spec=spec_str,
            file_samples=samples_str,
        )

        if settings.llm_advisory_only:
            await self._collect_llm_advisory(DOCKERFILE_FRONTEND_SYSTEM, user_prompt, "dockerfile_frontend")
            return self._deterministic_frontend_dockerfile(analysis)

        raw = None
        try:
            raw = await llm_client.generate(DOCKERFILE_FRONTEND_SYSTEM, user_prompt)
        except Exception as exc:
            raise DockerError(f"LLM failed to generate a frontend Dockerfile: {exc}") from exc
        dockerfile = extract_text_content(raw)

        if not dockerfile or "FROM" not in dockerfile.upper():
            raise DockerError("LLM failed to generate a frontend Dockerfile")

        return dockerfile

    # ── Backend Dockerfile ───────────────────────────────────────

    async def generate_backend_dockerfile(
        self,
        analysis: ProjectAnalysis,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
    ) -> str:
        """Generate a Dockerfile specifically for the BACKEND."""
        be_info = json.dumps(analysis.backend_info or {}, indent=2, ensure_ascii=False)
        spec_str = json.dumps(build_spec, indent=2, ensure_ascii=False)
        samples_str = _format_samples(file_samples)

        user_prompt = DOCKERFILE_BACKEND_USER.format(
            backend_info=be_info,
            build_spec=spec_str,
            file_samples=samples_str,
        )

        if settings.llm_advisory_only:
            await self._collect_llm_advisory(DOCKERFILE_BACKEND_SYSTEM, user_prompt, "dockerfile_backend")
            return self._deterministic_backend_dockerfile(analysis)

        raw = None
        try:
            raw = await llm_client.generate(DOCKERFILE_BACKEND_SYSTEM, user_prompt)
            dockerfile = extract_text_content(raw)
        except Exception as exc:
            raise DockerError(f"LLM failed to generate a backend Dockerfile: {exc}") from exc

        if not dockerfile or "FROM" not in dockerfile.upper():
            raise DockerError("LLM failed to generate a backend Dockerfile")

        return dockerfile

    # ── Repair ───────────────────────────────────────────────────

    async def repair_dockerfile(
        self,
        dockerfile: str,
        error: str,
        build_spec: Dict[str, Any],
        file_samples: Dict[str, str],
    ) -> str:
        """Send build error back to LLM and ask for a fix."""
        if settings.llm_advisory_only:
            logger.info("Skipping LLM repair in advisory-only mode; keeping deterministic Dockerfile policy.")
            return dockerfile

        spec_str = json.dumps(build_spec, indent=2, ensure_ascii=False)
        samples_str = _format_samples(file_samples)

        user_prompt = REPAIR_USER.format(
            dockerfile=dockerfile,
            error=error[:3000],
            build_spec=spec_str,
            file_samples=samples_str,
        )

        try:
            raw = await llm_client.generate(REPAIR_SYSTEM, user_prompt)
        except Exception as exc:
            raise DockerError(f"LLM failed to repair the Dockerfile: {exc}") from exc
        repaired = extract_text_content(raw)

        if not repaired or "FROM" not in repaired.upper():
            raise DockerError("LLM failed to repair the Dockerfile")

        return repaired

    # ── Fallback defaults ────────────────────────────────────────

    def _default_build_spec(self, analysis: ProjectAnalysis) -> Dict[str, Any]:
        """Generate a default build spec using detected versions for correct base images."""
        fe = analysis.frontend_info or {}
        be = analysis.backend_info or {}
        pt = analysis.project_type

        # Resolve base images from detected versions
        node_image = self._resolve_node_image(fe, be)
        backend_image = self._resolve_backend_image(be)

        spec: Dict[str, Any] = {
            "base_image": backend_image or node_image,
            "modules": [],
            "environment": {},
            "needs_database": False,
            "database_type": None,
        }

        if pt in ("frontend-only", "static-html"):
            pm = fe.get("package_manager", "npm")
            spec["base_image"] = node_image
            spec["modules"].append({
                "type": "frontend",
                "path": fe.get("path", "."),
                "install": f"{pm} install",
                "build": fe.get("build_command") or f"{pm} run build",
                "run": {"command": f"npx serve -s build -l {fe.get('port', 3000)}", "port": fe.get("port", 3000)},
            })

        elif pt == "backend-only":
            spec["base_image"] = backend_image
            lang = be.get("language", "python")
            fw = be.get("framework", "")
            run_cmd = be.get("run_command") or self._default_run_command(lang, fw, be.get("port", 8000))
            install = self._default_install(lang, be.get("package_manager"))
            spec["modules"].append({
                "type": "backend",
                "path": be.get("path", "."),
                "install": install,
                "build": None,
                "run": {"command": run_cmd, "port": be.get("port", 8000)},
            })

        elif pt == "fullstack":
            pm = fe.get("package_manager", "npm")
            lang = be.get("language", "python")
            fw = be.get("framework", "")
            spec["modules"] = [
                {
                    "type": "backend",
                    "path": be.get("path", "backend"),
                    "install": self._default_install(lang, be.get("package_manager")),
                    "build": None,
                    "run": {
                        "command": be.get("run_command") or self._default_run_command(lang, fw, be.get("port", 8000)),
                        "port": be.get("port", 8000),
                    },
                },
                {
                    "type": "frontend",
                    "path": fe.get("path", "frontend"),
                    "install": f"{pm} install",
                    "build": fe.get("build_command") or f"{pm} run build",
                    "run": {"command": f"npx serve -s build -l {fe.get('port', 3000)}", "port": fe.get("port", 3000)},
                },
            ]

        if analysis.database_info and analysis.database_info.get("detected"):
            spec["needs_database"] = True
            spec["database_type"] = analysis.database_info.get("type")

        return spec

    def _deterministic_frontend_dockerfile(self, analysis: ProjectAnalysis) -> str:
        fe = analysis.frontend_info or {}
        frontend_path = fe.get("path") or "frontend"
        frontend_port = int(fe.get("port", 3000) or 3000)
        package_manager = fe.get("package_manager") or "npm"
        install_cmd = "npm ci" if package_manager == "npm" else f"{package_manager} install"
        build_cmd = fe.get("build_command") or f"{package_manager} run build"

        lines = [
            "FROM node:20-alpine AS builder",
            "WORKDIR /app",
            f"COPY {frontend_path}/package*.json ./",
            f"RUN {install_cmd}",
            f"COPY {frontend_path}/ ./",
            f"RUN {build_cmd}",
            "FROM nginx:alpine",
            "RUN apk add --no-cache curl",
            "RUN printf '%s\\n' \\",
            f"  'server {{' \\",
            f"  '  listen {frontend_port};' \\",
            "  '  server_name _;' \\",
            "  '  root /usr/share/nginx/html;' \\",
            "  '  index index.html;' \\",
            "  '  location / {' \\",
            "  '    try_files $uri $uri/ /index.html;' \\",
            "  '  }' \\",
            "  '}' \\",
            "  > /etc/nginx/conf.d/default.conf",
            "COPY --from=builder /app/dist /usr/share/nginx/html",
            f"EXPOSE {frontend_port}",
            "HEALTHCHECK --interval=10s --timeout=4s --start-period=15s --retries=10 \\",
            f"  CMD curl -sf http://127.0.0.1:{frontend_port}/ || exit 1",
            "CMD [\"nginx\", \"-g\", \"daemon off;\"]",
        ]
        return "\n".join(lines) + "\n"

    def _deterministic_backend_dockerfile(self, analysis: ProjectAnalysis) -> str:
        be = analysis.backend_info or {}
        backend_path = be.get("path") or "backend"
        port = int(be.get("port", 8000) or 8000)
        language = (be.get("language") or "").lower()

        if language == "python":
            lines = [
                "FROM python:3.12-slim",
                "WORKDIR /app",
                "RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*",
                f"COPY {backend_path}/requirements*.txt ./",
                "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi",
                f"COPY {backend_path}/ ./",
                f"EXPOSE {port}",
                "HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=12 \\",
                f"  CMD curl -sf http://127.0.0.1:{port}/health || curl -sf http://127.0.0.1:{port}/ || exit 1",
                f"CMD [\"python\", \"main.py\"]",
            ]
            return "\n".join(lines) + "\n"

        lines = [
            "FROM node:20-alpine",
            "RUN apk add --no-cache curl",
            "WORKDIR /app",
            "RUN test -f .env || touch .env",
            f"COPY {backend_path}/package*.json ./",
            "RUN npm ci",
            f"COPY {backend_path}/ ./",
            f"EXPOSE {port}",
            "HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=12 \\",
            f"  CMD curl -sf http://127.0.0.1:{port}/health || curl -sf http://127.0.0.1:{port}/ || exit 1",
            "CMD [\"npm\", \"start\"]",
        ]
        return "\n".join(lines) + "\n"

    def _resolve_node_image(self, fe: dict, be: dict) -> str:
        """Pick node Docker image based on detected version."""
        ver = fe.get("node_version") or be.get("language_version")
        if ver:
            major = ver.split(".")[0]
            return f"node:{major}-alpine"
        return "node:20-alpine"

    def _resolve_backend_image(self, be: dict) -> str:
        """Pick backend Docker image based on detected language + version."""
        lang = be.get("language", "")
        ver = be.get("language_version", "")

        if lang == "python":
            if ver:
                # e.g. "3.11" → "python:3.11-slim"
                return f"python:{ver}-slim"
            return "python:3.12-slim"

        if lang == "java":
            if ver:
                return f"eclipse-temurin:{ver}-jdk-alpine"
            return "eclipse-temurin:21-jdk-alpine"

        if lang == "php":
            if ver:
                major = ver.split(".")[0]
                return f"php:{major}-fpm-alpine"
            return "php:8.3-fpm-alpine"

        if lang == "go":
            if ver:
                return f"golang:{ver}-alpine"
            return "golang:1.22-alpine"

        if lang in ("javascript", "typescript"):
            return self._resolve_node_image({}, be)

        return "node:20-alpine"

    def _default_run_command(self, lang: str, fw: str, port: int) -> str:
        """Return a sensible default run command."""
        commands = {
            "fastapi": f"uvicorn main:app --host 0.0.0.0 --port {port}",
            "django": f"python manage.py runserver 0.0.0.0:{port}",
            "flask": f"flask run --host 0.0.0.0 --port {port}",
            "express": "npm start",
            "nestjs": "npm run start:prod",
            "fastify": "npm start",
            "spring-boot": "java -jar target/*.jar",
            "laravel": f"php artisan serve --host 0.0.0.0 --port {port}",
            "lumen": f"php -S 0.0.0.0:{port} -t public",
            "gin": f"./app",
            "fiber": f"./app",
            "echo": f"./app",
            "chi": f"./app",
            "go-stdlib": f"./app",
        }
        return commands.get(fw, "npm start" if lang in ("javascript", "typescript") else f"python main.py")

    def _default_install(self, lang: str, pm: str | None = None) -> str:
        if lang == "python":
            return "pip install -r requirements.txt"
        if lang == "java":
            return "mvn install -DskipTests"
        if lang == "php":
            return "composer install --no-dev"
        if lang == "go":
            return "go build -o app ."
        return f"{pm or 'npm'} install"


def _format_samples(samples: Dict[str, str]) -> str:
    return "\n\n".join(f"### {k}\n```\n{v}\n```" for k, v in samples.items())


# Singleton
docker_generator = DockerGenerator()
