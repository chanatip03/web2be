"""Deterministic heuristic-based project analysis with full version detection.

Detects frameworks AND their versions by reading actual dependency files:
- package.json    → React, Vue, Angular, Next.js, Svelte, Express, NestJS + node version
- requirements.txt / pyproject.toml → Django, FastAPI, Flask + python version
- pom.xml / build.gradle → Spring Boot + java version
- composer.json   → Laravel, Symfony, Lumen + php version
- go.mod          → Gin, Fiber, Echo, Chi + go version
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.deployment.models.project import ProjectAnalysis

logger = logging.getLogger(__name__)


def analyze_heuristic(project_path: Path) -> ProjectAnalysis:
    """Detect project type, framework, versions, and ports from file-system heuristics."""
    frontend_info = _detect_frontend(project_path)
    backend_info = _detect_backend(project_path)
    database_info = _detect_database(project_path)

    has_fe = frontend_info.get("detected", False)
    has_be = backend_info.get("detected", False)

    if has_fe and has_be:
        project_type = "fullstack"
    elif has_fe:
        project_type = "frontend-only"
    elif has_be:
        project_type = "backend-only"
    else:
        project_type = "static-html" if _has_html(project_path) else "backend-only"

    # Build tech stack with versions
    tech_stack: List[str] = []
    if frontend_info.get("framework"):
        fw = frontend_info["framework"]
        ver = frontend_info.get("framework_version", "")
        tech_stack.append(f"{fw}@{ver}" if ver else fw)
    if backend_info.get("framework"):
        fw = backend_info["framework"]
        ver = backend_info.get("framework_version", "")
        tech_stack.append(f"{fw}@{ver}" if ver else fw)
    if backend_info.get("language"):
        lang = backend_info["language"]
        ver = backend_info.get("language_version", "")
        tech_stack.append(f"{lang}@{ver}" if ver else lang)

    ports: Dict[str, int] = {}
    if frontend_info.get("port"):
        ports["frontend"] = frontend_info["port"]
    if backend_info.get("port"):
        ports["backend"] = backend_info["port"]

    # Build commands
    run_commands: Dict[str, str] = {}
    build_steps: List[str] = []

    if has_fe:
        pm = frontend_info.get("package_manager", "npm")
        build_cmd = frontend_info.get("build_command")
        dev_cmd = frontend_info.get("dev_command")
        run_commands["frontend"] = dev_cmd or f"{pm} run dev"
        if build_cmd:
            build_steps.append(f"Frontend: {build_cmd}")

    if has_be:
        run_cmd = backend_info.get("run_command")
        if run_cmd:
            run_commands["backend"] = run_cmd

    return ProjectAnalysis(
        project_type=project_type,
        frontend_info=frontend_info if has_fe else None,
        backend_info=backend_info if has_be else None,
        database_info=database_info if database_info.get("detected") else None,
        tech_stack=tech_stack,
        recommended_ports=ports,
        run_commands=run_commands,
        build_steps=build_steps,
        is_static_site=project_type == "static-html",
        summary=_build_summary(project_type, frontend_info, backend_info, database_info),
    )


def _build_summary(ptype, fe, be, db) -> str:
    parts = [f"Type: {ptype}"]
    if fe.get("detected"):
        parts.append(f"Frontend: {fe.get('framework')}@{fe.get('framework_version', '?')}")
    if be.get("detected"):
        parts.append(f"Backend: {be.get('framework')}@{be.get('framework_version', '?')} ({be.get('language')}@{be.get('language_version', '?')})")
    if db.get("detected"):
        parts.append(f"DB: {db.get('type')}")
    return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════════
# FRONTEND DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_frontend(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    pkg_paths = [root / "package.json", root / "frontend" / "package.json", root / "client" / "package.json"]
    pkg_path = next((p for p in pkg_paths if p.exists()), None)

    if not pkg_path:
        if _has_html(root):
            return {
                "detected": True, "framework": "static-html",
                "framework_version": None, "port": 80, "path": ".",
            }
        return info

    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return info

    all_deps: Dict[str, str] = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(data.get(key), dict):
            all_deps.update(data[key])

    # Detect framework + version
    framework_checks = [
        ("next",           "nextjs",  3000),
        ("react",          "react",   3000),
        ("vue",            "vue",     3000),
        ("@angular/core",  "angular", 4200),
        ("svelte",         "svelte",  5173),
    ]

    framework = None
    framework_version = None
    port = 3000

    for dep_name, fw_name, default_port in framework_checks:
        if dep_name in all_deps:
            framework = fw_name
            framework_version = _clean_semver(all_deps[dep_name])
            port = default_port
            break

    # Vite override port
    if "vite" in all_deps:
        port = 5173

    # Node version from .nvmrc, .node-version, or engines
    node_version = None
    for nv_file in (".nvmrc", ".node-version"):
        nv_path = pkg_path.parent / nv_file
        if nv_path.exists():
            node_version = nv_path.read_text(encoding="utf-8").strip().lstrip("v")
            break
    if not node_version:
        engines = data.get("engines", {})
        if isinstance(engines, dict) and "node" in engines:
            node_version = _clean_semver(engines["node"])

    # Package manager
    pm = _detect_package_manager(pkg_path.parent)

    # Build / dev commands from scripts
    scripts = data.get("scripts", {})
    build_command = None
    dev_command = None
    if isinstance(scripts, dict):
        build_command = f"{pm} run build" if "build" in scripts else None
        dev_command = f"{pm} run dev" if "dev" in scripts else (f"{pm} start" if "start" in scripts else None)

    # Entry point
    entry_point = data.get("main") or "index.js"

    rel_path = str(pkg_path.parent.relative_to(root)) if pkg_path.parent != root else "."
    info.update({
        "detected": True,
        "framework": framework or "unknown-js",
        "framework_version": framework_version,
        "node_version": node_version,
        "path": rel_path,
        "port": port,
        "package_manager": pm,
        "entry_point": entry_point,
        "build_command": build_command,
        "dev_command": dev_command,
    })
    return info


def _detect_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lockb").exists():
        return "bun"
    return "npm"


# ═══════════════════════════════════════════════════════════════════
# BACKEND DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_backend(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    # Try each language in priority order
    for detector in (_detect_python, _detect_java, _detect_node_backend, _detect_php, _detect_go):
        result = detector(root)
        if result.get("detected"):
            return result

    return info


# ── Python ───────────────────────────────────────────────────────

def _detect_python(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    search_dirs = [root, root / "backend", root / "server", root / "api"]
    manifest_path = None
    manifest_type = None

    for d in search_dirs:
        if (d / "requirements.txt").exists():
            manifest_path = d / "requirements.txt"
            manifest_type = "requirements"
            break
        if (d / "pyproject.toml").exists():
            manifest_path = d / "pyproject.toml"
            manifest_type = "pyproject"
            break
        if (d / "Pipfile").exists():
            manifest_path = d / "Pipfile"
            manifest_type = "pipfile"
            break

    if not manifest_path:
        return info

    text = manifest_path.read_text(encoding="utf-8", errors="ignore")

    # Detect framework + version
    framework = "python"
    framework_version = None

    fw_patterns = [
        (r"fastapi[=~><!\s]*([0-9][0-9.]*)?",    "fastapi"),
        (r"django[=~><!\s]*([0-9][0-9.]*)?",      "django"),
        (r"flask[=~><!\s]*([0-9][0-9.]*)?",        "flask"),
    ]

    for pattern, fw_name in fw_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            framework = fw_name
            framework_version = match.group(1) if match.group(1) else None
            break

    # Python version
    python_version = None
    # From pyproject.toml requires-python
    if manifest_type == "pyproject":
        ver_match = re.search(r'requires-python\s*=\s*"[><=!~]*([0-9.]+)', text)
        if ver_match:
            python_version = ver_match.group(1)
    # From runtime.txt (Heroku)
    runtime_path = manifest_path.parent / "runtime.txt"
    if runtime_path.exists():
        rt = runtime_path.read_text(encoding="utf-8").strip()
        ver_match = re.search(r"python-?([0-9.]+)", rt, re.IGNORECASE)
        if ver_match:
            python_version = ver_match.group(1)
    # From .python-version
    pyver_path = manifest_path.parent / ".python-version"
    if pyver_path.exists():
        python_version = pyver_path.read_text(encoding="utf-8").strip()

    # Detect port and run command
    port = 8000
    run_command = None
    main_file = None

    if framework == "fastapi":
        main_file = _find_python_main(manifest_path.parent, ["main.py", "app.py", "app/main.py", "src/main.py"])
        module = main_file.replace("/", ".").replace(".py", "") if main_file else "main"
        run_command = f"uvicorn {module}:app --host 0.0.0.0 --port 8000"
    elif framework == "django":
        port = 8000
        manage = _find_python_main(manifest_path.parent, ["manage.py"])
        run_command = "python manage.py runserver 0.0.0.0:8000"
    elif framework == "flask":
        port = 5000
        main_file = _find_python_main(manifest_path.parent, ["app.py", "run.py", "main.py", "wsgi.py"])
        run_command = f"flask run --host 0.0.0.0 --port 5000"

    rel_path = str(manifest_path.parent.relative_to(root)) if manifest_path.parent != root else "."
    return {
        "detected": True,
        "framework": framework,
        "framework_version": framework_version,
        "language": "python",
        "language_version": python_version,
        "path": rel_path,
        "port": port,
        "main_file": main_file,
        "run_command": run_command,
    }


def _find_python_main(base: Path, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if (base / c).exists():
            return c
    return None


# ── Java / Spring Boot ───────────────────────────────────────────

def _detect_java(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    search_dirs = [root, root / "backend", root / "server"]

    for d in search_dirs:
        # Maven
        pom = d / "pom.xml"
        if pom.exists():
            return _parse_pom(root, d, pom)

        # Gradle
        for gf in ("build.gradle", "build.gradle.kts"):
            gradle = d / gf
            if gradle.exists():
                return _parse_gradle(root, d, gradle)

    return info


def _parse_pom(root: Path, base: Path, pom_path: Path) -> Dict[str, Any]:
    text = pom_path.read_text(encoding="utf-8", errors="ignore")

    # Spring Boot version from parent
    spring_version = None
    sb_match = re.search(
        r"<parent>.*?spring-boot.*?<version>([0-9.]+)</version>",
        text, re.DOTALL | re.IGNORECASE,
    )
    if sb_match:
        spring_version = sb_match.group(1)
    else:
        # Try spring-boot-starter dependency
        sb_dep = re.search(r"spring-boot-starter.*?<version>([0-9.]+)", text, re.DOTALL)
        if sb_dep:
            spring_version = sb_dep.group(1)

    framework = "spring-boot" if spring_version or "spring-boot" in text.lower() else "java-maven"

    # Java version
    java_version = None
    jv = re.search(r"<java\.version>([0-9.]+)</java\.version>", text)
    if jv:
        java_version = jv.group(1)
    else:
        jv = re.search(r"<maven\.compiler\.source>([0-9.]+)", text)
        if jv:
            java_version = jv.group(1)

    # Port from application.properties
    port = 8080
    for props_name in ("application.properties", "application.yml", "application.yaml"):
        props = base / "src" / "main" / "resources" / props_name
        if props.exists():
            pt = props.read_text(encoding="utf-8", errors="ignore")
            pm = re.search(r"server\.port\s*[=:]\s*(\d+)", pt)
            if pm:
                port = int(pm.group(1))

    rel_path = str(base.relative_to(root)) if base != root else "."
    return {
        "detected": True,
        "framework": framework,
        "framework_version": spring_version,
        "language": "java",
        "language_version": java_version,
        "path": rel_path,
        "port": port,
        "run_command": "mvn spring-boot:run" if framework == "spring-boot" else "mvn exec:java",
    }


def _parse_gradle(root: Path, base: Path, gradle_path: Path) -> Dict[str, Any]:
    text = gradle_path.read_text(encoding="utf-8", errors="ignore")

    spring_version = None
    sv = re.search(r"org\.springframework\.boot.*?version\s*['\"]([0-9.]+)", text)
    if sv:
        spring_version = sv.group(1)

    framework = "spring-boot" if spring_version or "spring-boot" in text.lower() else "java-gradle"

    java_version = None
    jv = re.search(r"(?:sourceCompatibility|java\s*\{[^}]*version)\s*[='\"]\s*(\d+)", text)
    if jv:
        java_version = jv.group(1)

    rel_path = str(base.relative_to(root)) if base != root else "."
    return {
        "detected": True,
        "framework": framework,
        "framework_version": spring_version,
        "language": "java",
        "language_version": java_version,
        "path": rel_path,
        "port": 8080,
        "run_command": "./gradlew bootRun" if framework == "spring-boot" else "./gradlew run",
    }


# ── Node.js backend (Express / NestJS) ──────────────────────────

def _detect_node_backend(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    def _infer_port_from_source(pkg_dir: Path, scripts: Dict[str, Any]) -> Optional[int]:
        candidates: List[str] = []
        if isinstance(scripts, dict):
            joined = "\n".join(str(v) for v in scripts.values() if isinstance(v, str))
            # Extract file paths from scripts (best-effort)
            for m in re.findall(r"([\w./-]+\.(?:ts|js))", joined):
                candidates.append(m)

        candidates.extend([
            "src/index.ts",
            "src/server.ts",
            "src/main.ts",
            "src/index.js",
            "index.js",
            "server.js",
            "app.js",
        ])

        seen: set[str] = set()
        for rel in candidates:
            if rel in seen:
                continue
            seen.add(rel)
            p = pkg_dir / rel
            if not p.exists() or not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            patterns = [
                r"process\.env\.PORT\s*\|\|\s*(\d{2,5})",
                r"\bport\s*[:=]\s*(\d{2,5})\b",
                r"\.listen\(\s*(\d{2,5})\b",
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    try:
                        return int(m.group(1))
                    except Exception:
                        continue
        return None

    for pkg_dir in [root / "backend", root / "server", root]:
        pkg_path = pkg_dir / "package.json"
        if not pkg_path.exists():
            continue

        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        deps: Dict[str, str] = {}
        for key in ("dependencies", "devDependencies"):
            if isinstance(data.get(key), dict):
                deps.update(data[key])

        # Framework detection
        node_frameworks = [
            ("@nestjs/core",       "nestjs",   "typescript"),
            ("express",            "express",  "javascript"),
            ("fastify",            "fastify",  "javascript"),
            ("koa",                "koa",      "javascript"),
            ("hapi",               "hapi",     "javascript"),
            ("hono",               "hono",     "typescript"),
            ("@hono/node-server",  "hono",     "typescript"),
        ]

        for dep_name, fw_name, lang in node_frameworks:
            if dep_name in deps:
                version = _clean_semver(deps[dep_name])
                pm = _detect_package_manager(pkg_dir)
                scripts = data.get("scripts", {})
                run_cmd = f"{pm} start" if "start" in scripts else f"{pm} run dev"

                # Try to find port from scripts and/or entrypoint source
                port = 3000
                start_script = (scripts.get("start", "") if isinstance(scripts, dict) else "")
                dev_script = (scripts.get("dev", "") if isinstance(scripts, dict) else "")
                pm_match = re.search(r"--port\s+(\d+)", f"{start_script} {dev_script}")
                if pm_match:
                    port = int(pm_match.group(1))
                else:
                    inferred = _infer_port_from_source(pkg_dir, scripts if isinstance(scripts, dict) else {})
                    if inferred:
                        port = inferred

                # Node version
                node_version = None
                engines = data.get("engines", {})
                if isinstance(engines, dict) and "node" in engines:
                    node_version = _clean_semver(engines["node"])

                rel_path = str(pkg_dir.relative_to(root)) if pkg_dir != root else "."
                return {
                    "detected": True,
                    "framework": fw_name,
                    "framework_version": version,
                    "language": lang,
                    "language_version": node_version,
                    "path": rel_path,
                    "port": port,
                    "run_command": run_cmd,
                    "package_manager": pm,
                }

    return info


# ── PHP (Laravel / Symfony / Lumen) ──────────────────────────────

def _detect_php(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    for d in [root, root / "backend"]:
        composer = d / "composer.json"
        if not composer.exists():
            continue

        try:
            data = json.loads(composer.read_text(encoding="utf-8"))
        except Exception:
            continue

        deps = data.get("require", {})

        # Framework detection
        php_frameworks = [
            ("laravel/framework",   "laravel"),
            ("laravel/lumen",       "lumen"),
            ("symfony/framework-bundle", "symfony"),
        ]

        framework = "php"
        framework_version = None
        for dep_name, fw_name in php_frameworks:
            if dep_name in deps:
                framework = fw_name
                framework_version = _clean_semver(deps[dep_name])
                break

        # PHP version
        php_version = None
        if "php" in deps:
            php_version = _clean_semver(deps["php"])

        port = 8000
        run_command = "php artisan serve --host 0.0.0.0 --port 8000" if framework in ("laravel", "lumen") else "php -S 0.0.0.0:8000 -t public"

        rel_path = str(d.relative_to(root)) if d != root else "."
        return {
            "detected": True,
            "framework": framework,
            "framework_version": framework_version,
            "language": "php",
            "language_version": php_version,
            "path": rel_path,
            "port": port,
            "run_command": run_command,
        }

    return info


# ── Go (Gin / Fiber / Echo / Chi / Standard) ────────────────────

def _detect_go(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False}

    for d in [root, root / "backend", root / "server"]:
        gomod = d / "go.mod"
        if not gomod.exists():
            continue

        text = gomod.read_text(encoding="utf-8", errors="ignore")

        # Go version
        go_version = None
        gv = re.search(r"^go\s+([0-9.]+)", text, re.MULTILINE)
        if gv:
            go_version = gv.group(1)

        # Framework detection from require block
        go_frameworks = [
            ("github.com/gin-gonic/gin",     "gin"),
            ("github.com/gofiber/fiber",     "fiber"),
            ("github.com/labstack/echo",     "echo"),
            ("github.com/go-chi/chi",        "chi"),
            ("github.com/gorilla/mux",       "gorilla"),
        ]

        framework = "go-stdlib"
        framework_version = None

        for module, fw_name in go_frameworks:
            # Match: github.com/gin-gonic/gin v1.9.1
            pattern = rf"{re.escape(module)}\s+v?([0-9][0-9.]*)"
            match = re.search(pattern, text)
            if match:
                framework = fw_name
                framework_version = match.group(1)
                break
            # Also check for module path without version (indirect)
            if module in text:
                framework = fw_name
                break

        # Try to find port from main.go
        port = 8080
        main_go = d / "main.go"
        if main_go.exists():
            mg = main_go.read_text(encoding="utf-8", errors="ignore")
            pm = re.search(r"[:.](\d{4,5})", mg)
            if pm:
                p = int(pm.group(1))
                if 1024 <= p <= 65535:
                    port = p

        rel_path = str(d.relative_to(root)) if d != root else "."
        return {
            "detected": True,
            "framework": framework,
            "framework_version": framework_version,
            "language": "go",
            "language_version": go_version,
            "path": rel_path,
            "port": port,
            "run_command": "go run .",
        }

    return info


# ═══════════════════════════════════════════════════════════════════
# DATABASE DETECTION
# ═══════════════════════════════════════════════════════════════════

def _detect_database(root: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"detected": False, "type": None}

    # Check docker-compose
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        compose_path = root / name
        if compose_path.exists():
            text = compose_path.read_text(encoding="utf-8", errors="ignore").lower()
            if "postgres" in text:
                return {"detected": True, "type": "postgresql"}
            if "mysql" in text or "mariadb" in text:
                return {"detected": True, "type": "mysql"}
            if "mongo" in text:
                return {"detected": True, "type": "mongodb"}
            if "redis" in text:
                return {"detected": True, "type": "redis"}

    # Check .env files
    for env_name in (".env.example", ".env", ".env.local"):
        env_path = root / env_name
        if env_path.exists():
            text = env_path.read_text(encoding="utf-8", errors="ignore").lower()
            if "postgres" in text or "pg_" in text:
                return {"detected": True, "type": "postgresql"}
            if "mysql" in text:
                return {"detected": True, "type": "mysql"}
            if "mongo" in text:
                return {"detected": True, "type": "mongodb"}

    # Check dependency files for DB drivers
    for dep_file in ("requirements.txt", "package.json", "composer.json"):
        dep_path = root / dep_file
        if dep_path.exists():
            text = dep_path.read_text(encoding="utf-8", errors="ignore").lower()
            if "psycopg" in text or "pg " in text or '"pg"' in text:
                return {"detected": True, "type": "postgresql"}
            if "mysql" in text or "pymysql" in text:
                return {"detected": True, "type": "mysql"}
            if "mongo" in text or "pymongo" in text:
                return {"detected": True, "type": "mongodb"}
            if "sqlite" in text:
                return {"detected": True, "type": "sqlite"}

    return info


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _clean_semver(raw: str) -> Optional[str]:
    """Extract the numeric version from a semver string like '^18.2.0' or '>=3.12'."""
    if not raw:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)*)", raw)
    return match.group(1) if match else None


def _has_html(root: Path) -> bool:
    return any(
        (root / p).exists()
        for p in ("index.html", "frontend/index.html", "public/index.html", "src/index.html")
    )
