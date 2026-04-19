"""Centralised prompt templates for all LLM tasks.

Keeping prompts in one place makes them easy to review, tweak, and test.
Each constant is a *template* with ``{placeholders}`` filled at call-site.
"""

# ── Project Analysis ─────────────────────────────────────────────

ANALYSIS_SYSTEM = """\
You are a senior software architect specialising in containerised deployments.
Analyse the repository below and return a **single JSON object** that conforms
to the following schema (no markdown fences, no extra text).

CRITICAL — Version Detection Rules:
- READ `.nvmrc`, `.node-version`, `.tool-versions` to detect the EXACT Node.js version.
- READ `package.json` → `"engines"` field for Node/npm version constraints.
- READ `pyproject.toml` → `[tool.poetry.dependencies] python = "..."` or `[project] requires-python`.
- READ `.python-version` for the exact Python version.
- READ `go.mod` → `go X.Y` line for Go version.
- READ `pom.xml` → `<java.version>` or `<maven.compiler.source>` for Java version.
- READ `composer.json` → `"require": {"php": "..."}` for PHP version.
- Populate `language_version` in `backend_info` and `node_version` in `frontend_info` with EXACT detected versions.
- These versions will be directly used as Docker base image tags — accuracy is critical.

{
  "project_type": "frontend-only" | "backend-only" | "fullstack" | "static-html",
  "frontend_info": {
    "detected": bool,
    "framework": str | null,   // react | vue | angular | nextjs | svelte | static-html | null
    "path": str,
    "entry_point": str | null,
    "build_command": str | null,
    "dev_command": str | null,
    "package_manager": "npm" | "yarn" | "pnpm" | "none",
    "port": int | null,
    "node_version": str | null  // EXACT version from .nvmrc/.node-version/package.json engines e.g. "18", "20", "22"
  },
  "backend_info": {
    "detected": bool,
    "framework": str | null,   // fastapi | django | flask | express | nestjs | spring-boot | laravel | null
    "language": str | null,
    "path": str,
    "main_file": str | null,
    "run_command": str | null,
    "port": int | null,
    "language_version": str | null  // EXACT version e.g. "3.11", "3.12", "18", "20", "21", "1.22"
  },
  "database_info": {
    "detected": bool,
    "type": str | null,        // postgresql | mysql | mongodb | sqlite | null
    "connection_env": str | null
  },
  "tech_stack": [str],
  "entry_points": {"frontend": str, "backend": str},
  "dependencies": {"frontend": [str], "backend": [str]},
  "recommended_ports": {"frontend": int, "backend": int},
  "build_steps": [str],
  "run_commands": {"frontend": str, "backend": str},
  "environment_variables": [str],
  "is_static_site": bool,
  "deployment_strategy": "docker",
  "summary": str
}
"""

ANALYSIS_USER = """\
## Intent Hint
The user expects this project to be: **{hint_type}**
(Please prioritize this type unless the file structure clearly contradicts it)

## File tree
{file_tree}

## Key file contents
{file_samples}
"""

# ── Build Spec Generation ────────────────────────────────────────

BUILD_SPEC_SYSTEM = """\
You are a Docker deployment expert. Given the project analysis and file context,
produce a **JSON build specification** that describes how to build and run this
project inside Docker containers. Return ONLY valid JSON (no markdown fences).

Required JSON structure:
{
  "base_image": str,           // e.g. "node:20-alpine", "python:3.12-slim"
  "modules": [
    {
      "type": "frontend" | "backend",
      "path": str,             // relative path to module root
      "install": str,          // install command e.g. "npm ci"
      "build": str | null,     // build command e.g. "npm run build"
      "run": {
        "command": str,        // start command
        "port": int
      }
    }
  ],
  "environment": {str: str},   // default env vars
  "needs_database": bool,
  "database_type": str | null
}
"""

BUILD_SPEC_USER = """\
## Analysis
{analysis}

## File tree
{file_tree}

## Key files
{file_samples}
"""

# ── Dockerfile Generation ────────────────────────────────────────

DOCKERFILE_SYSTEM = """\
You are a Docker expert. Generate a **production-ready Dockerfile** for the
project described below. Output ONLY the Dockerfile content — no markdown
fences, no explanatory text.

CRITICAL — Base Image Version Rules:
- Use the EXACT version from the analysis `language_version` / `node_version` field as the Docker image tag.
- If analysis says node_version="18", use `node:18-alpine` NOT `node:20-alpine`.
- If analysis says language_version="3.11", use `python:3.11-slim` NOT `python:3.12-slim`.
- If analysis says language_version="21", use `eclipse-temurin:21-jdk-alpine` for Java.
- NEVER use a different version than what is detected from the project source files.
- Check the key files (package.json engines, .nvmrc, requirements.txt, pyproject.toml) to confirm versions.

Requirements:
- Use multi-stage builds where beneficial
- Install dependencies before copying source for cache efficiency
- Use HEALTHCHECK instruction
- EXPOSE the correct port(s)
- Use a non-root USER when practical
- Keep the image as small as possible
"""

DOCKERFILE_USER = """\
Project type: {project_type}
Deploy mode: {deploy_mode}

## Analysis
{analysis}

## Build spec
{build_spec}

## Key files
{file_samples}
"""

# ── Mode-specific Dockerfile Generation ──────────────────────────

DOCKERFILE_FRONTEND_SYSTEM = """\
You are a Docker expert specialising in frontend applications.
Generate a production-ready Dockerfile that ONLY builds and serves the FRONTEND.
Ignore any backend code in the repository. Serve static files using nginx or
a static file server.

Output ONLY the Dockerfile content — no markdown fences, no explanation.

CRITICAL — Base Image Version Rules:
- Use the EXACT node_version from frontend_info as the builder stage tag.
- If node_version="18", use `node:18-alpine` NOT `node:20-alpine`.
- If node_version="20" or "lts", use `node:20-alpine`.
- Check .nvmrc, .node-version, and package.json engines field in the key files to confirm.

Requirements:
- Build the frontend (npm/yarn/pnpm run build)
- Serve via nginx:alpine or a lightweight static server
- EXPOSE the correct port (typically 80 or 3000)
- HEALTHCHECK instruction
- Non-root USER
"""

DOCKERFILE_FRONTEND_USER = """\
## Frontend info
{frontend_info}

## Build spec
{build_spec}

## Key files (frontend only)
{file_samples}
"""

DOCKERFILE_BACKEND_SYSTEM = """\
You are a Docker expert specialising in backend applications.
Generate a production-ready Dockerfile that ONLY builds and runs the BACKEND.
Ignore any frontend code in the repository.

Output ONLY the Dockerfile content — no markdown fences, no explanation.

CRITICAL — Base Image Version Rules:
- Use the EXACT language_version from backend_info as the Docker image tag.
- Python 3.11 → `python:3.11-slim`, Python 3.12 → `python:3.12-slim`.
- Node 18 → `node:18-alpine`, Node 20 → `node:20-alpine`.
- Java 21 → `eclipse-temurin:21-jdk-alpine`.
- PHP 8.2 → `php:8.2-fpm-alpine`.
- Check requirements.txt, pyproject.toml, package.json, .nvmrc, composer.json to confirm.

Requirements:
- Install backend dependencies only
- Run the backend server (e.g. uvicorn, gunicorn, npm start)
- EXPOSE the correct port (typically 8000 or 3000)
- HEALTHCHECK instruction
- Non-root USER
"""

DOCKERFILE_BACKEND_USER = """\
## Backend info
{backend_info}

## Build spec
{build_spec}

## Key files (backend only)
{file_samples}
"""

# ── Dockerfile Repair ────────────────────────────────────────────

REPAIR_SYSTEM = """\
The Docker build for this project FAILED. Study the error, then output a
corrected Dockerfile that fixes the issue. Output ONLY the Dockerfile —
no fences, no explanations.
"""

REPAIR_USER = """\
## Previous Dockerfile
{dockerfile}

## Build error
{error}

## Build spec
{build_spec}

## Key files
{file_samples}
"""

# ── Docker-compose Generation ────────────────────────────────────

COMPOSE_SYSTEM = """\
Generate a docker-compose.yml for the following multi-service project.
Output ONLY the YAML content — no markdown fences.
Include appropriate health checks, networks, and depends_on.
"""

COMPOSE_USER = """\
## Analysis
{analysis}

## Build spec
{build_spec}

## Service images
{service_images}
"""

# ── Environment Variable Generation ─────────────────────────────

ENV_GEN_SYSTEM = """\
You are a DevOps expert. Analyse the project source code below and generate
a complete `.env` file with all environment variables the application needs to
run inside Docker containers.

Rules:
- Scan for `process.env.X`, `os.environ["X"]`, `os.getenv("X")`, `env("X")`,
  `@Value`, `Config` classes, `.env.example`, and similar patterns.
- For each variable, provide a **realistic mock/development value** that would
  make the application run successfully in a local Docker environment.
- For database URLs, use Docker-internal hostnames (e.g. `db`, `redis`),
  default ports, and simple credentials (user=app, password=app_secret).
- For API keys / secrets, use placeholder strings like `dev-secret-key-change-me`.
- For URLs, use `http://localhost` or Docker service names.
- Include `NODE_ENV=production` or `ENVIRONMENT=production` as appropriate.
- Output ONLY the `.env` file content — no markdown fences, no explanation.
- One variable per line in KEY=VALUE format.
- Add short comments (# ...) to group related variables.
"""

ENV_GEN_USER = """\
## Project analysis
{analysis}

## File tree
{file_tree}

## Key source files (look for env variable references)
{file_samples}
"""

