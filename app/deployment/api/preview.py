"""Preview reverse-proxy — routes requests to running containers per project and service.

Supports:
- Multi-project: each project gets unique host ports, no conflicts
- Multi-service: /preview/{project_id}/frontend/... → frontend container
                 /preview/{project_id}/backend/...  → backend container
                 /preview/{project_id}/...           → primary service (frontend first)
- HTTP reverse proxy with link rewriting
- WebSocket proxy for HMR
"""

from __future__ import annotations

import asyncio
import posixpath
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, FileResponse

from app.deployment.core.config import settings
from app.deployment.services.deployer.pipeline import deployment_store, project_store
from app.deployment.services.docker.client import docker_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Preview"])


_PREVIEW_PROJECT_COOKIE = "preview_project_id"


_UUID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _infer_project_id_from_referer(request: Request) -> Optional[str]:
    referer = request.headers.get("referer") or request.headers.get("referrer")
    if not referer:
        return None

    match = re.search(
        r"(?i)/preview/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)",
        referer,
    )
    if not match:
        return None
    project_id = match.group(1)
    if not _UUID_RE.match(project_id):
        return None
    return project_id


def _infer_single_running_project_id() -> Optional[str]:
    running = [
        d for d in deployment_store.list_all()
        if (d.status in {"running", "success"}) and d.project_id
    ]
    if len(running) == 1:
        return running[0].project_id
    return None


def _infer_latest_running_project_id(*, prefer_frontend: bool = False) -> Optional[str]:
    candidates = [
        d
        for d in deployment_store.list_all()
        if (d.status in {"running", "success"}) and d.project_id
    ]
    if prefer_frontend:
        filtered = []
        for d in candidates:
            mode = (d.deploy_mode or "").lower()
            if mode == "backend-only":
                continue
            filtered.append(d)
        candidates = filtered

        # If we have any explicitly fullstack deployments, prefer them.
        fullstack = [d for d in candidates if (d.deploy_mode or "").lower() == "fullstack"]
        if fullstack:
            candidates = fullstack

    if not candidates:
        return None

    best = max(
        candidates,
        key=lambda d: (
            1 if (d.status or "").lower() == "running" else 0,
            d.updated_at or datetime.min,
        ),
    )
    return best.project_id


def _infer_project_id_from_request(request: Request) -> Optional[str]:
    project_id = _infer_project_id_from_referer(request)
    if project_id:
        return project_id
    cookie = request.cookies.get(_PREVIEW_PROJECT_COOKIE)
    if cookie and _UUID_RE.match(cookie):
        return cookie
    # Avoid cross-project collisions: only infer without context when there is
    # exactly one active deployment.
    return _infer_single_running_project_id()


def _infer_project_id_for_frontend_compat(request: Request) -> Optional[str]:
    """Infer a project id for root-level SPA route compatibility redirects.

    We avoid redirecting into backend-only deployments (which can't serve pages
    like /register), preferring fullstack deployments when multiple are active.
    """
    project_id = _infer_project_id_from_referer(request)
    if project_id and _UUID_RE.match(project_id):
        dep = _find_deployment(project_id)
        if dep and (dep.deploy_mode or "").lower() != "backend-only":
            return project_id

    cookie = request.cookies.get(_PREVIEW_PROJECT_COOKIE)
    if cookie and _UUID_RE.match(cookie):
        dep = _find_deployment(cookie)
        if dep and (dep.deploy_mode or "").lower() != "backend-only":
            return cookie

    return _infer_latest_running_project_id(prefer_frontend=True)


@router.get("/register")
@router.get("/login")
async def root_spa_route_compat(request: Request):
    """Compat: redirect common SPA routes at the public base domain.

    The deployer serves projects under /preview/{project_id}/..., but some apps
    (or users) may navigate directly to /register or /login.
    """
    page = (request.url.path or "/").lstrip("/")
    project_id = _infer_project_id_for_frontend_compat(request)
    if not project_id:
        return JSONResponse(
            status_code=404,
            content={
                "detail": "No active preview deployment to route to. Open a preview URL first (e.g. /preview/<id>/) to set context.",
            },
        )

    return RedirectResponse(
        url=f"/preview/{project_id}/{page}",
        status_code=307,
    )


def _extract_go_gin_endpoints(server_src: str) -> list[dict[str, Any]]:
    """Best-effort extractor for Gin route registrations in Go code."""
    prefix_by_var: dict[str, str] = {"router": ""}

    group_pat = re.compile(
        r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*(?::=|=)\s*(?P<parent>[A-Za-z_][A-Za-z0-9_]*)\.Group\(\s*\"(?P<prefix>[^\"]*)\"\s*\)",
        flags=re.MULTILINE,
    )
    for m in group_pat.finditer(server_src):
        var = m.group("var")
        parent = m.group("parent")
        group_prefix = m.group("prefix")
        parent_prefix = prefix_by_var.get(parent, "")
        prefix_by_var[var] = _normalize_joined_path(parent_prefix, group_prefix)

    route_pat = re.compile(
        r"^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\(\s*\"(?P<path>[^\"]+)\"",
        flags=re.MULTILINE,
    )

    endpoints: list[dict[str, Any]] = []
    for m in route_pat.finditer(server_src):
        var = m.group("var")
        method = m.group("method").upper()
        path = m.group("path")
        prefix = prefix_by_var.get(var, "")
        endpoints.append({"method": method, "path": _normalize_joined_path(prefix, path)})

    dedup = {(ep.get("method"), ep.get("path")): ep for ep in endpoints if ep.get("method") and ep.get("path")}
    return list(dedup.values())


def _extract_go_route_file_endpoints(backend_root: Path) -> list[dict[str, Any]]:
    routes_dir = backend_root / "routes"
    if not routes_dir.exists() or not routes_dir.is_dir():
        return []

    endpoints: list[dict[str, Any]] = []
    route_pat = re.compile(
        r"\b[A-Za-z_][A-Za-z0-9_]*\.(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\(\s*\"([^\"]+)\"",
        flags=re.IGNORECASE,
    )
    for go_file in routes_dir.rglob("*.go"):
        try:
            src = go_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in route_pat.finditer(src):
            method = m.group(1).upper()
            path = m.group(2)
            if not path.startswith("/"):
                path = f"/{path}"
            endpoints.append({"method": method, "path": _normalize_joined_path("", path)})

    dedup = {(ep.get("method"), ep.get("path")): ep for ep in endpoints if ep.get("method") and ep.get("path")}
    return list(dedup.values())


def _api_test_html(project_id: str, *, backend_prefix: str) -> str:
        # Keep this page intentionally minimal: one form + a couple of presets.
        return f"""<!doctype html>
<html>
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>API Test: {project_id[:8]}</title>
        <style>
            body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 900px; margin: 24px auto; padding: 0 16px; }}
            h1 {{ margin: 0 0 8px; }}
            .muted {{ color: #64748b; font-size: 14px; }}
            label {{ display: block; font-weight: 600; margin: 14px 0 6px; }}
            input, select, textarea {{ width: 100%; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }}
            textarea {{ height: 220px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
            .row {{ display: grid; grid-template-columns: 160px 1fr; gap: 10px; }}
            button {{ margin-top: 12px; padding: 10px 14px; border: 0; border-radius: 10px; background: #2563eb; color: white; font-weight: 700; cursor: pointer; }}
            pre {{ background: #0b1220; color: #e2e8f0; padding: 12px; border-radius: 10px; overflow: auto; }}
            .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; font-weight: 700; }}
        </style>
    </head>
    <body>
        <h1>API Test <span class=\"pill\">{project_id[:8]}</span></h1>
        <p class=\"muted\">Sends requests through the preview proxy to the backend service.</p>

        <label>Preset</label>
        <select id=\"preset\">
            <option value=\"register\">POST /users/register (create user)</option>
            <option value=\"login\">POST /users/login (login)</option>
            <option value=\"ping\">GET / (API ping)</option>
        </select>

        <label>Request</label>
        <div class=\"row\">
            <select id=\"method\">
                <option>GET</option>
                <option selected>POST</option>
                <option>PUT</option>
                <option>DELETE</option>
                <option>PATCH</option>
            </select>
            <input id=\"path\" value=\"/users/register\" />
        </div>

        <label>JSON Body (optional)</label>
        <textarea id=\"body\"></textarea>

        <button id=\"send\">Send</button>

        <label>Result</label>
        <pre id=\"out\">(not sent yet)</pre>

        <script>
            const backendPrefix = {backend_prefix!r};
            const presetEl = document.getElementById('preset');
            const methodEl = document.getElementById('method');
            const pathEl = document.getElementById('path');
            const bodyEl = document.getElementById('body');
            const outEl = document.getElementById('out');

            const sampleRegister = {{
                user_name: 'demo_user',
                first_name: 'Demo',
                last_name: 'User',
                user_email: `demo_${{Math.floor(Math.random() * 1e9)}}@example.com`,
                user_password: 'password123'
            }};
            const sampleLogin = {{
                user_email: 'demo@example.com',
                user_password: 'password123'
            }};

            function applyPreset() {{
                const v = presetEl.value;
                if (v === 'register') {{
                    methodEl.value = 'POST';
                    pathEl.value = '/users/register';
                    bodyEl.value = JSON.stringify(sampleRegister, null, 2);
                }} else if (v === 'login') {{
                    methodEl.value = 'POST';
                    pathEl.value = '/users/login';
                    bodyEl.value = JSON.stringify(sampleLogin, null, 2);
                }} else {{
                    methodEl.value = 'GET';
                    pathEl.value = '/';
                    bodyEl.value = '';
                }}
            }}

            presetEl.addEventListener('change', applyPreset);
            applyPreset();

            document.getElementById('send').addEventListener('click', async () => {{
                outEl.textContent = 'Sending...';
                const method = methodEl.value;
                const path = pathEl.value.startsWith('/') ? pathEl.value : '/' + pathEl.value;
                const url = backendPrefix + path;

                let payload = null;
                const raw = bodyEl.value.trim();
                if (raw) {{
                    try {{ payload = JSON.parse(raw); }} catch (e) {{
                        outEl.textContent = 'Invalid JSON body: ' + e;
                        return;
                    }}
                }}

                const headers = {{}};
                let body = undefined;
                if (payload !== null && method !== 'GET' && method !== 'HEAD') {{
                    headers['Content-Type'] = 'application/json';
                    body = JSON.stringify(payload);
                }}

                try {{
                    const resp = await fetch(url, {{ method, headers, body }});
                    const ct = resp.headers.get('content-type') || '';
                    let text = await resp.text();
                    if (ct.includes('application/json')) {{
                        try {{ text = JSON.stringify(JSON.parse(text), null, 2); }} catch {{}}
                    }}
                    outEl.textContent = `HTTP ${{resp.status}}\n\n${{text}}`;
                }} catch (e) {{
                    outEl.textContent = 'Request failed: ' + e;
                }}
            }});
        </script>
    </body>
</html>"""


def _extract_backend_endpoints(project_id: str) -> list[dict[str, Any]]:
    project = project_store.get(project_id)
    if not project or not project.analysis:
        return []

    backend_info = project.analysis.backend_info or {}
    raw = backend_info.get("api_endpoints") or []
    endpoints: list[dict[str, Any]] = []

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                method = str(item.get("method") or "GET").upper()
                path = str(item.get("path") or item.get("url") or "/")
            else:
                text = str(item).strip()
                parts = text.split(maxsplit=1)
                method = parts[0].upper() if parts and parts[0].isalpha() and len(parts[0]) <= 8 else "GET"
                path = parts[1] if len(parts) > 1 else text

            if not path.startswith("/"):
                path = f"/{path}"
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
                method = "GET"

            endpoints.append({"method": method, "path": path})

    file_endpoints = _extract_backend_endpoints_from_files(project_id)
    endpoints.extend(file_endpoints)

    dedup = {(ep.get("method"), ep.get("path")): ep for ep in endpoints if ep.get("method") and ep.get("path")}
    return list(dedup.values())


def _normalize_joined_path(prefix: str, subpath: str) -> str:
    p1 = (prefix or "").strip()
    p2 = (subpath or "").strip()
    if not p1.startswith("/"):
        p1 = f"/{p1}" if p1 else ""
    if p1.endswith("/") and p1 != "/":
        p1 = p1[:-1]
    if not p2.startswith("/"):
        p2 = f"/{p2}" if p2 else ""
    full = f"{p1}{p2}" or "/"
    full = re.sub(r"//+", "/", full)
    return full


def _extract_backend_endpoints_from_files(project_id: str) -> list[dict[str, Any]]:
    root = Path(settings.projects_dir) / project_id
    project = project_store.get(project_id)
    backend_path = None
    if project and project.analysis:
        backend_path = (project.analysis.backend_info or {}).get("path")

    candidates = []
    if backend_path:
        candidates.append(root / backend_path)
    candidates.append(root / "backend")
    candidates.append(root)

    server_file = None
    server_kind: str | None = None
    for base in candidates:
        if not base.exists():
            continue

        go_main = base / "main.go"
        if go_main.exists():
            server_file = go_main
            server_kind = "go"
            break

        # Support common server entrypoints across JS/TS frameworks.
        for candidate in (
            "server.js",
            "app.js",
            "index.js",
            "server.ts",
            "app.ts",
            "index.ts",
            "src/server.js",
            "src/app.js",
            "src/index.js",
            "src/server.ts",
            "src/app.ts",
            "src/index.ts",
            "src/main.ts",
            "main.ts",
        ):
            path = (base / candidate)
            if path.exists():
                server_file = path
                server_kind = "js"
                break
        if server_file:
            break

    if server_file is None:
        return []

    try:
        server_src = server_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    if server_kind == "go":
        endpoints = _extract_go_gin_endpoints(server_src)
        endpoints.extend(_extract_go_route_file_endpoints(server_file.parent))
        dedup = {(ep.get("method"), ep.get("path")): ep for ep in endpoints if ep.get("method") and ep.get("path")}
        return list(dedup.values())

    require_map: dict[str, Path] = {}
    for var, req in re.findall(r"const\s+(\w+)\s*=\s*require\(['\"]([^'\"]+)['\"]\)", server_src):
        if not req.startswith("."):
            continue
        route_path = (server_file.parent / req).resolve()
        if route_path.is_dir():
            route_path = route_path / "index.js"
        elif route_path.suffix == "":
            route_path = route_path.with_suffix(".js")
        require_map[var] = route_path

    # ESM/TypeScript import map: `import { userRoute } from './routes/users'`
    import_map: dict[str, Path] = {}
    for var, imp in re.findall(
        r"import\s*\{\s*(\w+)\s*\}\s*from\s*['\"]([^'\"]+)['\"]",
        server_src,
    ):
        if not imp.startswith("."):
            continue
        route_path = (server_file.parent / imp).resolve()
        if route_path.is_dir():
            # Best-effort: common patterns
            for leaf in ("index.ts", "index.js"):
                p = route_path / leaf
                if p.exists():
                    route_path = p
                    break
        elif route_path.suffix == "":
            # Try TS first then JS
            ts = route_path.with_suffix(".ts")
            js = route_path.with_suffix(".js")
            if ts.exists():
                route_path = ts
            else:
                route_path = js
        import_map[var] = route_path

    service_routes: list[tuple[str, Path]] = []
    for prefix, var in re.findall(r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)\s*\)", server_src):
        route_file = require_map.get(var)
        if route_file and route_file.exists():
            service_routes.append((prefix, route_file))

    # Hono-style route mounts: `app.route('/users', userRoute)`
    hono_routes: list[tuple[str, str, Path]] = []
    for prefix, var in re.findall(
        r"\bapp\.route\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\w+)\s*\)",
        server_src,
    ):
        route_file = import_map.get(var)
        if route_file and route_file.exists():
            hono_routes.append((prefix, var, route_file))

    endpoints: list[dict[str, Any]] = []

    def _extract_body_fields(handler_src: str) -> list[str]:
        match = re.search(r"const\s*{\s*([^}]+)\s*}\s*=\s*req\.body\s*;?", handler_src)
        if not match:
            return []
        raw = match.group(1)
        fields: list[str] = []
        for token in raw.split(","):
            name = token.strip()
            if not name:
                continue
            # Handle renaming/defaults: `a: b`, `a = 1`
            name = name.split(":", 1)[0].split("=", 1)[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                fields.append(name)
        # Dedup preserving order
        seen = set()
        out: list[str] = []
        for f in fields:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    for method, path in re.findall(r"app\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]", server_src, flags=re.IGNORECASE):
        endpoints.append({"method": method.upper(), "path": _normalize_joined_path("", path)})

    route_pattern = re.compile(
        r"router\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]",
        flags=re.IGNORECASE,
    )
    for prefix, route_file in service_routes:
        try:
            src = route_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        matches = list(route_pattern.finditer(src))
        for index, m in enumerate(matches):
            method = m.group(1).upper()
            path = m.group(2)
            start = m.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else min(len(src), start + 4000)
            handler_chunk = src[start:end]

            body_fields: list[str] = []
            if method in {"POST", "PUT", "PATCH"}:
                body_fields = _extract_body_fields(handler_chunk)

            endpoints.append({
                "method": method,
                "path": _normalize_joined_path(prefix, path),
                "body_fields": body_fields,
            })

    # Hono routes: scan the mounted route files for `<var>.<method>('/path', ...)`
    for prefix, var, route_file in hono_routes:
        try:
            src = route_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # e.g. userRoute.get('/', ...)
        method_pattern = re.compile(
            rf"\b{re.escape(var)}\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]+)['\"]",
            flags=re.IGNORECASE,
        )
        for m in method_pattern.finditer(src):
            method = m.group(1).upper()
            path = m.group(2)
            endpoints.append({
                "method": method,
                "path": _normalize_joined_path(prefix, path),
            })

    dedup = {(ep["method"], ep["path"]): ep for ep in endpoints}
    return list(dedup.values())


def _build_openapi_doc(project_id: str, deployment) -> dict[str, Any]:
    backend_prefix = f"/preview/{project_id}/backend"
    if deployment and deployment.deploy_mode == "backend-only":
        backend_prefix = f"/preview/{project_id}"

    def _express_path_to_openapi(path: str) -> str:
        # Express style params: /users/:id -> /users/{id}
        return re.sub(r"/:([A-Za-z0-9_]+)", r"/{\1}", path)

    def _openapi_path_params(path: str) -> list[dict[str, Any]]:
        params = []
        for name in re.findall(r"{([A-Za-z0-9_]+)}", path):
            # Many projects use string IDs (UUID/ObjectId). Use a realistic example.
            example = "507f1f77bcf86cd799439011" if (name.lower().endswith("id") or name.lower() == "id") else "value"
            params.append({
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string", "example": example},
            })
        return params

    def _infer_field_schema(name: str) -> dict[str, Any]:
        n = (name or "").lower()
        if n.endswith("_id") or n in {"id", "user_id", "place_id", "category_id"}:
            return {"type": "string"}
        if any(tok in n for tok in ("score", "rating", "lat", "lng", "price", "amount")):
            return {"type": "number"}
        if any(tok in n for tok in ("is_", "has_", "enabled", "active")):
            return {"type": "boolean"}
        return {"type": "string"}

    def _example_for_field(name: str) -> Any:
        n = (name or "").lower()
        if "email" in n:
            return "demo@example.com"
        if "password" in n:
            return "password123"
        if n in {"user_name", "username"}:
            return "demo_user"
        if n in {"first_name", "firstname"}:
            return "Demo"
        if n in {"last_name", "lastname"}:
            return "User"
        if n.endswith("_id") or n in {"id", "user_id", "place_id", "category_id"}:
            return "507f1f77bcf86cd799439011"
        if "rating" in n:
            return 5
        if "score" in n:
            return 4.8
        if any(tok in n for tok in ("lat", "lng")):
            return 13.7563
        return "string"

    def _example_for_fields(fields: list[str], *, path: str) -> dict[str, Any]:
        # Endpoint-specific tweaks for common auth routes.
        p = (path or "").lower()
        if "/users/register" in p:
            return {
                "user_name": "demo_user",
                "first_name": "Demo",
                "last_name": "User",
                "user_email": "demo@example.com",
                "user_password": "password123",
            }
        if "/users/login" in p:
            return {
                "user_email": "demo@example.com",
                "user_password": "password123",
            }
        return {k: _example_for_field(k) for k in fields}

    def _default_body_example_for_path(path: str) -> dict[str, Any]:
        # Normalize :id style params (Gin) into {id} for matching.
        p = _express_path_to_openapi(path or "").lower()
        if "/auth/register" in p or "/users/register" in p:
            return {
                "email": "demo@example.com",
                "password": "password123",
                "name": "Demo User",
                "address": {
                    "addressLine": "123 ถนนสุขุมวิท",
                    "city": "Bangkok",
                    "province": "Bangkok",
                    "zipcode": "10110",
                    "country": "Thailand",
                    "lat": 13.7563,
                    "lng": 100.5018,
                },
            }
        if "/auth/login" in p or "/users/login" in p:
            return {"email": "demo@example.com", "password": "password123", "remember_me": True}
        if "/auth/change-password" in p:
            # Gin handler expects: currentPassword + newPassword
            return {"currentPassword": "password123", "newPassword": "newpass123"}
        if "/profile" == p or p.endswith("/profile"):
            return {
                "name": "Demo User",
                "address": {
                    "addressLine": "123 ถนนสุขุมวิท",
                    "city": "Bangkok",
                    "province": "Bangkok",
                    "zipcode": "10110",
                    "country": "Thailand",
                    "lat": 13.7563,
                    "lng": 100.5018,
                },
            }
        if "/routes/suggest" in p:
            return {
                "start_location": "Phuket",
                "end_location": "Bangkok",
                "description": "Prefer scenic route and avoid tolls",
            }
        if "/routes/cost" in p:
            return {
                "start_location": "Phuket",
                "end_location": "Bangkok",
                "distance": 862.5,
                "duration": 660,
            }
        if p.endswith("/reviews") and "/api/reviews" in p:
            return {
                "placeId": "sample-place-001",
                "placeName": "Sample Place",
                "rating": 5,
                "comment": "Great place!",
            }
        if "/comments" in p and p.endswith("/comments"):
            return {"text": "Nice review!"}
        if p.endswith("/report"):
            return {"type": "spam", "detail": "Contains advertising links"}
        if p in {"/api/admin/places", "/api/admin/places/{id}"} or p.endswith("/admin/places"):
            return {
                "name": "Demo Place",
                "description": "A nice place to visit.",
                "location_id": "LOC-001",
                "category": "Attraction",
                "address": "Bangkok, Thailand",
                "phone": "+66-2-000-0000",
                "website": "https://example.com",
                "hours": "09:00-18:00",
                "coverImage": "uploads/CoverImage/demo.jpg",
                "highlights": ["uploads/HighlightImages/a.jpg"],
                "coordinates": {"lat": 13.7563, "lng": 100.5018},
            }
        if "/admin/users" in p and p.endswith("/ban"):
            return {"reason": "Violation of community guidelines"}
        if p.endswith("/admin/users/{id}"):
            return {"name": "Demo User", "role": "user"}
        if "/review-reports" in p and p.endswith("/status"):
            return {"status": "resolved"}
        if p.endswith("/reviews/{id}"):
            return {"rating": 5, "comment": "Updated comment"}
        return {}

    def _default_body_schema_for_path(path: str) -> dict[str, Any] | None:
        """Best-effort schema when we can't infer fields statically.

        This keeps Swagger UI usable (Schema + Example) for common endpoints.
        """
        # Normalize :id style params (Gin) into {id} for matching.
        p = _express_path_to_openapi(path or "").lower()
        if "/auth/register" in p or "/users/register" in p:
            return {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "password": {"type": "string", "minLength": 7},
                    "name": {"type": "string"},
                    "address": {
                        "type": "object",
                        "properties": {
                            "addressLine": {"type": "string"},
                            "city": {"type": "string"},
                            "province": {"type": "string"},
                            "zipcode": {"type": "string"},
                            "country": {"type": "string"},
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                        },
                        "required": ["lat", "lng"],
                    },
                },
                "required": ["email", "password", "name", "address"],
            }
        if "/auth/login" in p or "/users/login" in p:
            return {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "password": {"type": "string"},
                    "remember_me": {"type": "boolean"},
                },
                "required": ["email", "password"],
            }
        if "/auth/change-password" in p:
            return {
                "type": "object",
                "properties": {
                    "currentPassword": {"type": "string"},
                    "newPassword": {"type": "string", "minLength": 7},
                },
                "required": ["currentPassword", "newPassword"],
            }
        if p == "/api/profile" or p.endswith("/profile"):
            return {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {
                        "type": "object",
                        "properties": {
                            "addressLine": {"type": "string"},
                            "city": {"type": "string"},
                            "province": {"type": "string"},
                            "zipcode": {"type": "string"},
                            "country": {"type": "string"},
                            "lat": {"type": "number"},
                            "lng": {"type": "number"},
                        },
                        "required": ["lat", "lng"],
                    },
                },
                "required": ["name", "address"],
            }
        if p.endswith("/routes/suggest"):
            return {
                "type": "object",
                "properties": {
                    "start_location": {"type": "string"},
                    "end_location": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["start_location", "end_location"],
            }
        if p.endswith("/routes/cost"):
            return {
                "type": "object",
                "properties": {
                    "start_location": {"type": "string"},
                    "end_location": {"type": "string"},
                    "distance": {"type": "number"},
                    "duration": {"type": "integer", "description": "minutes"},
                },
                "required": ["start_location", "end_location", "distance", "duration"],
            }
        if p == "/api/reviews" or p.endswith("/reviews"):
            return {
                "type": "object",
                "properties": {
                    "placeId": {"type": "string"},
                    "placeName": {"type": "string"},
                    "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                    "comment": {"type": "string"},
                },
                "required": ["placeId", "rating", "comment"],
            }
        if p.endswith("/reviews/{id}"):
            return {
                "type": "object",
                "properties": {
                    "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                    "comment": {"type": "string"},
                },
                "required": ["rating", "comment"],
            }
        if p.endswith("/comments"):
            return {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }
        if p.endswith("/report"):
            return {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "e.g. spam, abuse"},
                    "detail": {"type": "string"},
                },
                "required": ["type"],
            }
        if p in {"/api/admin/places", "/api/admin/places/{id}"} or p.endswith("/admin/places"):
            return {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "location_id": {"type": "string"},
                    "category": {"type": "string"},
                    "address": {"type": "string"},
                    "phone": {"type": "string"},
                    "website": {"type": "string"},
                    "hours": {"type": "string"},
                    "coverImage": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                    "coordinates": {
                        "type": "object",
                        "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                    },
                },
                "required": ["name", "location_id"],
            }
        if p.endswith("/admin/users/{id}"):
            return {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string", "enum": ["user", "admin"]},
                },
                "required": ["name", "role"],
            }
        if p.endswith("/admin/users/{id}/ban"):
            return {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            }
        if p.endswith("/review-reports/{id}/status"):
            return {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["pending", "resolved", "rejected"]}},
                "required": ["status"],
            }
        return None

    def _default_query_params_for_path(openapi_path: str, method: str) -> list[dict[str, Any]]:
        p = (openapi_path or "").lower()
        if method == "GET" and p == "/api/reviews":
            return [
                {"name": "placeId", "in": "query", "required": False, "schema": {"type": "string"}, "example": "sample-place-001"},
                {"name": "rating", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 5}, "example": 5},
                {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}, "example": "great"},
                {"name": "sort", "in": "query", "required": False, "schema": {"type": "string", "enum": ["newest", "oldest", "highest", "lowest"]}, "example": "newest"},
            ]
        if method == "GET" and p == "/api/admin/review-reports":
            return [
                {"name": "status", "in": "query", "required": False, "schema": {"type": "string", "enum": ["pending", "resolved", "rejected"]}, "example": "pending"},
            ]
        if method == "POST" and p == "/api/admin/upload-image":
            return [
                {"name": "imgType", "in": "query", "required": False, "schema": {"type": "string", "enum": ["cover", "highlight"]}, "example": "cover"},
            ]
        return []

    def _multipart_upload_request_body() -> dict[str, Any]:
        return {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "image": {"type": "string", "format": "binary"},
                        },
                        "required": ["image"],
                    }
                }
            },
        }

    paths: dict[str, Any] = {}
    for ep in _extract_backend_endpoints(project_id):
        raw_path = str(ep.get("path") or "/")
        method = str(ep.get("method") or "GET").upper()
        body_fields = ep.get("body_fields") or []

        openapi_path = _express_path_to_openapi(raw_path)
        openapi_path_l = openapi_path.lower()
        op = {
            "summary": f"{method} {raw_path}",
            "responses": {
                "200": {"description": "Success"},
                "400": {"description": "Bad request"},
                "500": {"description": "Server error"},
            },
        }

        params = _openapi_path_params(openapi_path)
        if params:
            op["parameters"] = params

        # Add known query parameters for endpoints that use c.Query(...)
        query_params = _default_query_params_for_path(openapi_path, method)
        if query_params:
            op.setdefault("parameters", [])
            op["parameters"].extend(query_params)

        # Endpoints that are POST but do not accept a JSON body in this project.
        no_body_endpoints = {
            ("POST", "/api/auth/logout"),
            ("POST", "/api/auth/refresh"),
            ("POST", "/api/reviews/{id}/like"),
            ("POST", "/api/reviews/{id}/comments/{commentId}/like"),
            ("POST", "/api/admin/users/{id}/unban"),
        }

        # Multipart upload endpoint
        if method == "POST" and openapi_path_l == "/api/admin/upload-image":
            op["requestBody"] = _multipart_upload_request_body()

        # Some GET endpoints in Gin bind JSON from body (unusual but supported by the app).
        if method == "GET" and openapi_path_l == "/api/routes/cost":
            schema = _default_body_schema_for_path(raw_path) or {"type": "object", "additionalProperties": True}
            op["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": schema,
                        "example": _default_body_example_for_path(raw_path),
                    }
                },
            }

        if method in {"POST", "PUT", "PATCH"} and (method, openapi_path_l) not in no_body_endpoints and "requestBody" not in op:
            if isinstance(body_fields, list) and body_fields:
                schema_props = {k: _infer_field_schema(k) for k in body_fields}
                op["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": schema_props,
                                "required": body_fields,
                            },
                            "example": _example_for_fields(body_fields, path=raw_path),
                        }
                    },
                }
            else:
                # Best-effort: many backends require a JSON body even when we can't
                # statically infer fields (e.g. Go/Gin). Provide a generic object so
                # Swagger UI doesn't show "No parameters".
                schema = _default_body_schema_for_path(raw_path) or {"type": "object", "additionalProperties": True}
                op["requestBody"] = {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": schema,
                            "example": _default_body_example_for_path(raw_path),
                        }
                    },
                }

        paths.setdefault(openapi_path, {})[method.lower()] = op

    if not paths:
        paths = {
            "/": {
                "get": {
                    "summary": "Service root",
                    "responses": {"200": {"description": "Success"}},
                }
            }
        }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": f"{(deployment.project_name if deployment else project_id)} API",
            "version": "1.0.0",
            "description": "Auto-generated from project analysis in Backend V3.",
        },
        "servers": [{"url": backend_prefix}],
        "paths": paths,
    }


def _swagger_ui_html(project_id: str) -> str:
    spec_url = f"/preview/{project_id}/swagger.json"
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset=\"UTF-8\" />
  <title>Swagger UI - {project_id[:8]}</title>
  <link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\" />
  <style>body {{ margin: 0; background: #fafafa; }} #swagger-ui {{ margin: 0; }}</style>
</head>
<body>
  <div id=\"swagger-ui\"></div>
  <script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: \"{spec_url}\",
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis],
      layout: \"BaseLayout\"
    }});
  </script>
</body>
</html>"""


# ── Helpers ──────────────────────────────────────────────────────

def _find_deployment(project_id: str):
    """Find the active deployment for a project.

    Prefer a currently running deployment, otherwise pick the most recently
    updated successful deployment. This avoids routing to stale ports when a
    project has multiple historical "success" records.
    """
    all_deps = [dep for dep in deployment_store.list_all() if dep.project_id == project_id]
    if not all_deps:
        return None

    # Normal case: prefer running, then latest successful.
    candidates = [dep for dep in all_deps if (dep.status or "").lower() in ("running", "success")]
    if not candidates:
        # Resilience: after restarts, our state sync can temporarily mark
        # deployments as "stopped" even when the containers are still reachable.
        # Fall back to the most recently updated record.
        candidates = all_deps

    def _rank(d) -> tuple[int, datetime]:
        st = (d.status or "").lower()
        prio = 2 if st == "running" else (1 if st == "success" else 0)
        return (prio, d.updated_at or datetime.min)

    return max(candidates, key=_rank)


def _get_service_url(deployment, service: Optional[str] = None) -> Optional[str]:
    """Get the host URL for a specific service, or the primary service."""
    # If a specific service is requested, prefer exact match, then compose runtime.
    # This avoids accidentally routing to the DB when service_ports is incomplete.
    if service:
        if deployment.service_ports:
            for sp in deployment.service_ports:
                if sp.service == service:
                    return sp.url

        # Metadata can be stale after restart; recover from compose runtime.
        recovered = _resolve_service_url_from_compose(deployment, service)
        if recovered:
            return recovered

    if deployment.service_ports:
        # Fall back to primary: frontend > backend > app > first available
        for pref in ("frontend", "backend", "app"):
            for sp in deployment.service_ports:
                if sp.service == pref:
                    return sp.url

        return deployment.service_ports[0].url

    # Legacy fallback
    if deployment.preview_url:
        return deployment.preview_url.rstrip("/")
    if deployment.host_port:
        return f"http://localhost:{deployment.host_port}"
    if deployment.extra_ports:
        port = deployment.extra_ports[0].get("hostPort", 3000)
        return f"http://localhost:{port}"

    return None


def _resolve_service_url_from_compose(deployment, service: str) -> Optional[str]:
    project_name = getattr(deployment, "compose_project", None) or getattr(deployment, "project_id", None)
    if not project_name:
        return None
    try:
        containers = docker_client.client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={project_name}"},
        )
        for container in containers:
            labels = container.labels or {}
            if labels.get("com.docker.compose.service") != service:
                continue
            ports_data = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            for _, bindings in ports_data.items():
                if bindings:
                    host_port = int(bindings[0]["HostPort"])
                    return f"http://localhost:{host_port}"
    except Exception:
        return None
    return None


def _rewrite_html(html: str, prefix: str) -> str:
    """Rewrite relative URLs in HTML to route through preview proxy."""
    html = re.sub(
        r'((?:src|href|action)\s*=\s*["\'])(/)',
        rf"\1{prefix}/",
        html,
    )
    html = re.sub(
        r"""(fetch\s*\(\s*['"])(/[^'"]*['"])""",
        rf"\1{prefix}\2",
        html,
    )
    html = re.sub(
        r'(url\s*\(\s*["\']?)(/)',
        rf"\1{prefix}/",
        html,
    )
    return html


def _inject_preview_history_base(html: str, *, prefix: str) -> str:
    """Ensure SPA client-side navigation stays under the preview prefix.

    Some SPAs use client-side routing and call history.pushState('/places'),
    which changes the browser URL without a network request, bypassing our
    server-side redirects. This injection rewrites absolute same-origin paths
    to live under /preview/<id>/...
    """
    if not html or not prefix or not prefix.startswith("/preview/"):
        return html

    # Already injected?
    if "__preview_base_patch__" in html:
        return html

    script = f"""<script id=\"__preview_base_patch__\">\n(() => {{\n  const base = {prefix!r};\n  const fix = (u) => {{\n    try {{\n      if (typeof u !== 'string') return u;\n      if (!u.startsWith('/')) return u;\n      if (u.startsWith(base + '/')) return u;\n      if (u.startsWith('/preview/')) return u;\n      return base + u;\n    }} catch (_) {{\n      return u;\n    }}\n  }};\n\n  const p = history.pushState;\n  const r = history.replaceState;\n  history.pushState = function(state, title, url) {{\n    return p.apply(this, [state, title, fix(url)]);\n  }};\n  history.replaceState = function(state, title, url) {{\n    return r.apply(this, [state, title, fix(url)]);\n  }};\n\n  const a = window.location.assign.bind(window.location);\n  const rep = window.location.replace.bind(window.location);\n  window.location.assign = (url) => a(fix(url));\n  window.location.replace = (url) => rep(fix(url));\n}})();\n</script>"""

    # Prefer injecting before </head> when present.
    if "</head>" in html:
        return html.replace("</head>", script + "\n</head>", 1)
    return script + "\n" + html


def _rewrite_localhost_api(text: str, *, api_base: str) -> str:
    """Rewrite hardcoded localhost API origins to the preview backend prefix."""
    if not text or not api_base:
        return text
    # Broaden matching beyond the most common dev ports so more imported
    # projects keep working under preview without source edits.
    text = re.sub(
        r"(?i)https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d{1,5})?",
        api_base,
        text,
    )
    return text


def _rewrite_absolute_asset_paths(text: str, *, asset_base: str) -> str:
    """Rewrite absolute /assets/* paths to live under the preview prefix.

    Some Vite builds emit dynamic imports like "/assets/chunk.js" which break
    when served under /preview/<id>/.
    """
    if not text or not asset_base:
        return text

    # JS: "\/assets/..." or '/assets/...'
    text = re.sub(
        r'(["\'])/assets/',
        rf"\1{asset_base}/assets/",
        text,
    )
    # CSS: url(/assets/...)
    text = re.sub(
        r"url\(\s*/assets/",
        f"url({asset_base}/assets/",
        text,
    )
    return text


def _rewrite_common_project_asset_refs(text: str, *, prefix: str) -> str:
    """Rewrite common project-root asset folders to the preview prefix.

    Many imported projects reference shared files using paths like
    `../../img_place/foo.jpg`, `/uploads/bar.png`, or `./images/x.webp`.
    When served under `/preview/<id>/...`, converting these to absolute
    preview-prefixed URLs makes them independent of the current page depth.
    """
    if not text or not prefix or not prefix.startswith("/preview/"):
        return text

    dir_group = r"(img_place|uploads|images|image|img|imgs|media|public|static)"

    text = re.sub(
        rf'([`"\'])(?:\.\./|\./)*{dir_group}/',
        lambda m: f"{m.group(1)}{prefix}/{m.group(2)}/",
        text,
    )
    text = re.sub(
        rf'([`"\'])/{dir_group}/',
        lambda m: f"{m.group(1)}{prefix}/{m.group(2)}/",
        text,
    )
    text = re.sub(
        rf'url\(\s*(["\']?)(?:\.\./|\./)*{dir_group}/',
        lambda m: f"url({m.group(1)}{prefix}/{m.group(2)}/",
        text,
    )
    text = re.sub(
        rf'url\(\s*(["\']?)/{dir_group}/',
        lambda m: f"url({m.group(1)}{prefix}/{m.group(2)}/",
        text,
    )
    return text


def _normalize_preview_target(target: str, *, prefix: str, current_path: str = "") -> str:
    raw = (target or "").strip()
    if not raw:
        return raw

    quote = ""
    if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0]:
        quote = raw[0]
        raw = raw[1:-1].strip()

    lower = raw.lower()
    if (
        not raw
        or raw.startswith("/preview/")
        or raw.startswith(prefix)
        or raw.startswith("#")
        or lower.startswith(("http://", "https://", "data:", "mailto:", "tel:", "javascript:"))
    ):
        return target

    if raw.startswith("/"):
        rewritten = f"{prefix}{raw}"
    else:
        base_dir = "/" + posixpath.dirname((current_path or "").lstrip("/"))
        normalized = posixpath.normpath(posixpath.join(base_dir, raw))
        rewritten = f"{prefix}/{normalized.lstrip('/')}" if normalized not in {"", ".", "/"} else f"{prefix}/"

    return f"{quote}{rewritten}{quote}" if quote else rewritten


def _rewrite_meta_refresh_urls(html: str, *, prefix: str, current_path: str = "") -> str:
    if not html or not prefix:
        return html

    meta_pattern = re.compile(
        r'(?is)(<meta\b[^>]*http-equiv\s*=\s*["\']refresh["\'][^>]*content\s*=\s*["\'])([^"\']*)(["\'][^>]*>)'
    )

    def repl(match: re.Match[str]) -> str:
        content_value = match.group(2)

        def repl_url(url_match: re.Match[str]) -> str:
            return url_match.group(1) + _normalize_preview_target(
                url_match.group(2),
                prefix=prefix,
                current_path=current_path,
            )

        rewritten = re.sub(
            r'(?i)(\burl\s*=\s*)([^;]+)',
            repl_url,
            content_value,
            count=1,
        )
        return match.group(1) + rewritten + match.group(3)

    return meta_pattern.sub(repl, html)


def _rewrite_react_router_basename(js: str, *, prefix: str) -> str:
    """Best-effort patch for React Router basename in minified bundles.

    Many SPAs use React Router with default basename='/', which breaks when
    served under /preview/<id>/.... This attempts to detect the BrowserRouter
    component symbol (it uses v5Compat) and inject `basename: <prefix>` into
    its jsx() instantiation.
    """
    if not js or not prefix or not prefix.startswith("/preview/"):
        return js
    if "v5Compat:!0" not in js:
        return js

    # Detect the BrowserRouter symbol in the minified bundle.
    # BrowserRouter uses createBrowserHistory with v5Compat enabled.
    v_idx = js.find("v5Compat:!0")
    if v_idx == -1:
        return js

    window = js[max(0, v_idx - 3000) : v_idx + 200]
    # Find the last `function <sym>(e){let{basename:...` before the marker.
    sym = None
    for m in re.finditer(r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\(e\)\{let\{basename:", window):
        sym = m.group(1)
    if not sym:
        return js

    # Inject basename into the first jsx(sym,{...}) call if missing.
    needle = f"jsx({sym},{{"
    idx = js.find(needle)
    if idx == -1:
        return js
    after = js[idx + len(needle) : idx + len(needle) + 40]
    if "basename:" in after:
        return js

    return js.replace(needle, f"jsx({sym},{{basename:{prefix!r},", 1)


def _is_probably_static_asset(path: str) -> bool:
    p = (path or "").lstrip("/").lower()
    if not p:
        return False
    if p.startswith("assets/") or p.startswith("static/"):
        return True
    # Common file extensions served by the frontend container.
    for ext in (
        ".js",
        ".mjs",
        ".cjs",
        ".css",
        ".map",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".txt",
        ".json",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp4",
        ".webm",
        ".pdf",
    ):
        if p.endswith(ext):
            return True
    return False


def _normalized_filename_token(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _candidate_project_static_roots(project_id: str) -> list[Path]:
    project_root = Path(settings.projects_dir) / project_id
    roots: list[Path] = []
    seen: set[str] = set()

    project = project_store.get(project_id)
    detected_frontend_path = ""
    try:
        detected_frontend_path = str((getattr(getattr(project, "analysis", None), "frontend_info", None) or {}).get("path") or "").strip()
    except Exception:
        detected_frontend_path = ""

    candidates = [
        project_root / detected_frontend_path if detected_frontend_path else None,
        project_root / "frontend",
        project_root / "public",
        (project_root / detected_frontend_path / "public") if detected_frontend_path else None,
        project_root / "static",
        project_root / "assets",
        project_root,
    ]

    for candidate in candidates:
        if not candidate:
            continue
        try:
            resolved = str(candidate.resolve())
        except Exception:
            continue
        if resolved in seen or not candidate.exists():
            continue
        seen.add(resolved)
        roots.append(candidate)

    return roots


def _resolve_project_static_file(root: Path, relative_path: str) -> Optional[Path]:
    rel = (relative_path or "").lstrip("/")
    if not rel or not root.exists():
        return None

    rel_path = Path(rel)
    base_resolved = root.resolve()
    candidate = (root / rel_path).resolve()

    if str(candidate).startswith(str(base_resolved)) and candidate.is_file():
        return candidate

    parent = (root / rel_path.parent).resolve()
    if not (parent.is_dir() and str(parent).startswith(str(base_resolved)) and rel_path.name):
        return None

    target = _normalized_filename_token(rel_path.name)
    if not target:
        return None

    matches: list[Path] = []
    for item in parent.iterdir():
        if not item.is_file():
            continue
        if _normalized_filename_token(item.name) == target:
            matches.append(item)
            if len(matches) > 1:
                break
    return matches[0] if len(matches) == 1 else None


def _serve_project_static_file(project_id: str, relative_path: str) -> Optional[FileResponse]:
    rel = (relative_path or "").lstrip("/")
    if not rel:
        return None

    for root in _candidate_project_static_roots(project_id):
        try:
            resolved = _resolve_project_static_file(root, rel)
        except Exception:
            resolved = None
        if resolved is not None:
            return FileResponse(str(resolved))
    return None


async def _proxy_or_serve_root_project_static(request: Request, relative_path: str):
    project_id = _infer_project_id_from_request(request) or _infer_project_id_for_frontend_compat(request)
    if not project_id:
        return JSONResponse({"detail": f"Missing preview context for /{relative_path}"}, status_code=404)

    static_file = _serve_project_static_file(project_id, relative_path)
    if static_file is not None:
        return static_file

    head, _, tail = relative_path.partition("/")
    return await preview_service_proxy(project_id, head, request, tail)


def _backend_path_prefixes(project_id: str) -> set[str]:
    """Return first-segment prefixes for backend endpoints (best-effort)."""
    prefixes: set[str] = set()
    for ep in _extract_backend_endpoints(project_id):
        raw = str(ep.get("path") or "").strip()
        if not raw.startswith("/"):
            continue
        seg = raw.lstrip("/").split("/", 1)[0].strip()
        if seg:
            prefixes.add(seg)
    return prefixes


# ── Service listing ──────────────────────────────────────────────

@router.get("/preview/{project_id}")
@router.get("/preview/{project_id}/")
async def preview_index(project_id: str, request: Request):
    """Show available services for a project."""
    deployment = _find_deployment(project_id)
    if not deployment:
        return HTMLResponse("<h1>No active deployment</h1><p>Deploy the project first.</p>", 404)

    # Canonicalize to a trailing-slash URL before proxying.
    # Some static multi-page frontends issue relative redirects like
    # `home/home.html`; when the browser starts from `/preview/<id>` (no
    # trailing slash), it resolves them as `/preview/home/home.html` and loses
    # the project id.
    canonical_path = f"/preview/{project_id}/"
    if request.url.path == f"/preview/{project_id}":
        if request.url.query:
            return RedirectResponse(url=f"{canonical_path}?{request.url.query}", status_code=307)
        return RedirectResponse(url=canonical_path, status_code=307)

    deploy_mode = (deployment.deploy_mode or "").strip().lower()

    # UX parity with v1:
    # - frontend-only: open app directly
    # - backend-only: open Swagger directly
    # - fullstack: open frontend directly
    if deploy_mode == "backend-only":
        return HTMLResponse(_swagger_ui_html(project_id))

    if deploy_mode == "fullstack":
        base = _get_service_url(deployment, "frontend") or _get_service_url(deployment)
        if base:
            known = {sp.service for sp in (deployment.service_ports or [])}
            rewrite_api_base = f"/preview/{project_id}/backend" if "backend" in known else None
            return await _proxy_request_to(project_id, base, "", request, prefix=f"/preview/{project_id}", rewrite_api_base=rewrite_api_base)

    # Return service map as HTML or JSON
    services = []
    if deployment.service_ports:
        for sp in deployment.service_ports:
            services.append({
                "service": sp.service,
                "url": f"/preview/{project_id}/{sp.service}/",
                "direct_url": sp.url,
                "port": sp.host_port,
            })

    # If only one service, redirect directly
    if len(services) == 1:
        base = _get_service_url(deployment)
        if base:
            return await _proxy_request_to(project_id, base, "", request)

    if not services:
        return HTMLResponse("<h1>No services running</h1>", 502)

    # Show service selection page
    links = "".join(
        f'<a href="{s["url"]}" style="display:block;padding:16px 24px;margin:8px 0;'
        f'background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;'
        f'font-size:18px;">{s["service"]} → port {s["port"]}</a>'
        for s in services
    )

    html = f"""<!DOCTYPE html>
<html><head><title>Preview: {project_id[:8]}</title>
<style>body{{font-family:system-ui;max-width:600px;margin:40px auto;padding:20px;background:#0f172a;color:#e2e8f0}}
h1{{color:#60a5fa}} .info{{color:#94a3b8;font-size:14px}}</style></head>
<body>
<h1>🚀 Project {project_id[:8]}</h1>
<p class="info">Deploy mode: {deployment.deploy_mode}</p>
<h2>Available Services</h2>
{links}
</body></html>"""
    return HTMLResponse(html)


# ── Compatibility routes ─────────────────────────────────────────

@router.api_route(
    "/preview/img_place/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_img_place_compat(request: Request, path: str = ""):
    """Compat: handle /preview/img_place/... (missing project_id).

    Some projects hardcode paths like /preview/img_place/foo.jpg.
    We infer the project_id from Referer (which points to /preview/{project_id}/...)
    and route the request to that project's primary service.
    """
    project_id = _infer_project_id_from_referer(request) or _infer_single_running_project_id()
    if not project_id:
        return JSONResponse(
            {"detail": "Missing project id in /preview path. Use /preview/{project_id}/img_place/..."},
            status_code=404,
        )

    static_file = _serve_project_static_file(project_id, f"img_place/{path}" if path else "img_place")
    if static_file is not None:
        return static_file

    # Delegate to the normal service proxy: treating `img_place/...` as a path
    # under the project's primary service (frontend for fullstack).
    return await preview_service_proxy(project_id, "img_place", request, path)


@router.api_route(
    "/img_place/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/images/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/image/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/img/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/imgs/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/media/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/static/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/public/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_root_static_compat(path: str, request: Request):
    """Compat: serve common project-root asset folders at the public root.

    Imported projects often reference `/images/*`, `/img/*`, `/static/*`, or
    `/public/*` from the domain root. Under preview, infer the active project
    and serve those files from disk or proxy them through the frontend.
    """
    asset_prefix = request.url.path.lstrip("/").split("/", 1)[0]
    rel_path = f"{asset_prefix}/{path}" if path else asset_prefix
    return await _proxy_or_serve_root_project_static(request, rel_path)


@router.api_route("/favicon.ico", methods=["GET", "HEAD", "OPTIONS"])
@router.api_route("/robots.txt", methods=["GET", "HEAD", "OPTIONS"])
@router.api_route("/manifest.json", methods=["GET", "HEAD", "OPTIONS"])
@router.api_route("/site.webmanifest", methods=["GET", "HEAD", "OPTIONS"])
@router.api_route("/sw.js", methods=["GET", "HEAD", "OPTIONS"])
@router.api_route("/service-worker.js", methods=["GET", "HEAD", "OPTIONS"])
async def preview_root_singleton_static_compat(request: Request):
    """Compat: serve common root singleton static files for the active preview."""
    rel_path = request.url.path.lstrip("/")
    return await _proxy_or_serve_root_project_static(request, rel_path)


@router.api_route(
    "/preview/{project_id}/img_place/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_project_img_place(project_id: str, path: str, request: Request):
    """Serve project-root `img_place` assets under the preview prefix."""
    static_file = _serve_project_static_file(project_id, f"img_place/{path}" if path else "img_place")
    if static_file is not None:
        return static_file
    return await preview_service_proxy(project_id, "img_place", request, path)


@router.api_route(
    "/assets/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_assets_compat(path: str, request: Request):
    """Compat: proxy absolute /assets/* from preview-hosted SPAs.

    Some frontends emit absolute asset paths (e.g. /assets/chunk.js). When those
    apps are served under /preview/<id>/, the browser will request /assets/* at
    the deployer root. We infer the project id and forward to that project's
    frontend assets.
    """
    project_id = _infer_project_id_from_request(request)
    if not project_id:
        return JSONResponse({"detail": "Missing preview context for /assets/*"}, status_code=404)

    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)

    known = {sp.service for sp in (deployment.service_ports or [])}
    base = _get_service_url(deployment, "frontend") if "frontend" in known else _get_service_url(deployment)
    if not base:
        return JSONResponse({"detail": "No upstream port"}, status_code=502)

    rewrite_api_base = f"/preview/{project_id}/backend" if (deployment.deploy_mode == "fullstack" and "backend" in known) else None
    upstream_path = f"assets/{path}" if path else "assets"
    return await _proxy_request_to(
        project_id,
        base,
        upstream_path,
        request,
        prefix="/assets",
        rewrite_api_base=rewrite_api_base,
        strip_request_origin=False,
    )


@router.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def preview_absolute_api_proxy(path: str, request: Request):
    """Compat: proxy absolute /api/* from preview-hosted frontends.

    When an SPA is served at `/preview/<id>/` but calls `/api/...`, the browser
    will reach the deployer itself. We infer the preview project id and proxy
    the request to that project's backend.
    """
    project_id = _infer_project_id_from_request(request)
    if not project_id:
        return JSONResponse({"detail": "Missing preview context for /api/*"}, status_code=404)

    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)

    known = {sp.service for sp in (deployment.service_ports or [])}
    base: Optional[str] = None
    if deployment.deploy_mode in ("backend-only", "fullstack"):
        base = _get_service_url(deployment, "backend")
    if not base:
        base = _get_service_url(deployment, "backend") if "backend" in known else _get_service_url(deployment)

    if not base:
        return JSONResponse({"detail": "No upstream port"}, status_code=502)

    # Most backends mount routes under /api/..., so we normally forward
    # /api/<x> → upstream /api/<x>. Some clients accidentally call /api/api/<x>
    # (double prefix). Be permissive and avoid producing /api/api/<x> upstream.
    if not path:
        upstream_path = "api"
    elif path == "api" or path.startswith("api/"):
        upstream_path = path
    else:
        upstream_path = f"api/{path}"
    body_override: bytes | None = None
    if request.method.upper() in {"POST", "PUT", "PATCH"}:
        ct = (request.headers.get("content-type") or "").lower()
        if "application/json" in ct and upstream_path.rstrip("/") == "api/auth/register":
            try:
                raw = await request.body()
                data = json.loads(raw.decode("utf-8")) if raw else None
                if isinstance(data, dict) and "address" in data:
                    if data["address"] is None or isinstance(data["address"], str):
                        data["address"] = {}
                        body_override = json.dumps(data).encode("utf-8")
            except Exception:
                body_override = None

    return await _proxy_request_to(
        project_id,
        base,
        upstream_path,
        request,
        prefix="/api",
        rewrite_api_base=None,
        strip_request_origin=True,
        body_override=body_override,
    )


@router.api_route(
    "/undefined/api",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/undefined/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def preview_undefined_api_proxy(request: Request, path: str = ""):
    """Compat: proxy '/undefined/api/*' caused by bad client base URL concatenation."""
    project_id = _infer_project_id_from_request(request)
    if not project_id:
        return JSONResponse({"detail": "Missing preview context for /undefined/api/*"}, status_code=404)

    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)

    known = {sp.service for sp in (deployment.service_ports or [])}
    base: Optional[str] = None
    if deployment.deploy_mode in ("backend-only", "fullstack"):
        base = _get_service_url(deployment, "backend")
    if not base:
        base = _get_service_url(deployment, "backend") if "backend" in known else _get_service_url(deployment)

    if not base:
        return JSONResponse({"detail": "No upstream port"}, status_code=502)

    upstream_path = f"api/{path}" if path else "api"
    return await _proxy_request_to(
        project_id,
        base,
        upstream_path,
        request,
        prefix="/undefined/api",
        rewrite_api_base=None,
        strip_request_origin=True,
    )


@router.api_route(
    "/undefined/uploads/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
@router.api_route(
    "/uploads/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_uploads_compat(path: str, request: Request):
    """Compat: proxy uploads when client base URL is undefined or absolute.

    Some apps build image URLs as `${API_BASE}/uploads/...`. If API_BASE is
    undefined (or the app runs under /preview/<id>/), the browser may request
    /undefined/uploads/... or /uploads/... at the deployer root.
    """
    project_id = _infer_project_id_from_request(request)
    if not project_id:
        return JSONResponse({"detail": "Missing preview context for /uploads/*"}, status_code=404)

    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)

    known = {sp.service for sp in (deployment.service_ports or [])}
    base: Optional[str] = None
    if deployment.deploy_mode in ("backend-only", "fullstack"):
        base = _get_service_url(deployment, "backend")
    if not base:
        base = _get_service_url(deployment, "backend") if "backend" in known else _get_service_url(deployment)

    if not base:
        return JSONResponse({"detail": "No upstream port"}, status_code=502)

    upstream_path = f"uploads/{path}" if path else "uploads"
    prefix = "/undefined/uploads" if request.url.path.startswith("/undefined/uploads") else "/uploads"

    proxied = await _proxy_request_to(
        project_id,
        base,
        upstream_path,
        request,
        prefix=prefix,
        rewrite_api_base=None,
        strip_request_origin=True,
    )

    # If the backend container doesn't have the seeded upload files, serve from
    # the checked-out project directory as a last resort (read-only).
    if proxied.status_code == 404 and path:
        try:
            uploads_dir = Path(settings.projects_dir) / project_id / "backend" / "uploads"
            base_resolved = uploads_dir.resolve()
            candidate = (uploads_dir / path).resolve()

            if uploads_dir.exists() and str(candidate).startswith(str(base_resolved)) and candidate.is_file():
                return FileResponse(str(candidate))

            # Fuzzy match: sometimes the app requests filenames without hyphens.
            # Only search within the immediate parent directory.
            rel = Path(path)
            parent = (uploads_dir / rel.parent).resolve()
            if (
                uploads_dir.exists()
                and parent.is_dir()
                and str(parent).startswith(str(base_resolved))
                and rel.name
            ):
                def norm(s: str) -> str:
                    return "".join(ch.lower() for ch in s if ch.isalnum())

                target = norm(rel.name)
                if target:
                    matches: list[Path] = []
                    for p in parent.iterdir():
                        if not p.is_file():
                            continue
                        if norm(p.name) == target:
                            matches.append(p)
                            if len(matches) > 1:
                                break
                    if len(matches) == 1:
                        return FileResponse(str(matches[0]))
        except Exception:
            pass

    return proxied


@router.api_route(
    "/preview/{project_id}/uploads/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_project_uploads(project_id: str, path: str, request: Request):
    """Serve uploads under the preview prefix.

    Many frontends will request `/preview/<id>/uploads/...` (absolute from the
    preview root). Route that to the backend service, with the same disk
    fallback as the root-level `/uploads/*` compat.
    """
    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)

    known = {sp.service for sp in (deployment.service_ports or [])}
    base: Optional[str] = None
    if deployment.deploy_mode in ("backend-only", "fullstack"):
        base = _get_service_url(deployment, "backend")
    if not base:
        base = _get_service_url(deployment, "backend") if "backend" in known else _get_service_url(deployment)
    if not base:
        return JSONResponse({"detail": "No upstream port"}, status_code=502)

    upstream_path = f"uploads/{path}" if path else "uploads"
    proxied = await _proxy_request_to(
        project_id,
        base,
        upstream_path,
        request,
        prefix=f"/preview/{project_id}/uploads",
        rewrite_api_base=None,
        strip_request_origin=True,
    )

    if proxied.status_code == 404 and path:
        try:
            uploads_dir = Path(settings.projects_dir) / project_id / "backend" / "uploads"
            base_resolved = uploads_dir.resolve()
            candidate = (uploads_dir / path).resolve()
            if uploads_dir.exists() and str(candidate).startswith(str(base_resolved)) and candidate.is_file():
                return FileResponse(str(candidate))

            rel = Path(path)
            parent = (uploads_dir / rel.parent).resolve()
            if (
                uploads_dir.exists()
                and parent.is_dir()
                and str(parent).startswith(str(base_resolved))
                and rel.name
            ):
                def norm(s: str) -> str:
                    return "".join(ch.lower() for ch in s if ch.isalnum())

                target = norm(rel.name)
                if target:
                    matches: list[Path] = []
                    for p in parent.iterdir():
                        if not p.is_file():
                            continue
                        if norm(p.name) == target:
                            matches.append(p)
                            if len(matches) > 1:
                                break
                    if len(matches) == 1:
                        return FileResponse(str(matches[0]))
        except Exception:
            pass

    return proxied


@router.api_route(
    "/preview/{project_id}/{dup_project_id}/uploads/{path:path}",
    methods=["GET", "HEAD", "OPTIONS"],
)
async def preview_duplicate_project_uploads(
    project_id: str,
    dup_project_id: str,
    path: str,
    request: Request,
):
    """Compat: collapse `/preview/<id>/<id>/uploads/...` into `/preview/<id>/uploads/...`."""
    # Only treat this as a "duplicate id" compat path when the dup segment
    # looks like a UUID. Otherwise it may be a real service name (e.g. "backend")
    # and we must not hijack the request.
    if not _UUID_RE.match(dup_project_id):
        return await preview_service_proxy(project_id, dup_project_id, request, path=f"uploads/{path}" if path else "uploads")

    if dup_project_id == project_id:
        url = f"/preview/{project_id}/uploads/{path}" if path else f"/preview/{project_id}/uploads"
        if request.url.query:
            url += f"?{request.url.query}"
        return RedirectResponse(url=url, status_code=307)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@router.api_route(
    "/preview/{project_id}/{dup_project_id}/api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def preview_duplicate_project_api(
    project_id: str,
    dup_project_id: str,
    path: str,
    request: Request,
):
    """Compat: collapse `/preview/<id>/<id>/api/...` into `/preview/<id>/api/...`."""
    # Only treat this as a "duplicate id" compat path when the dup segment
    # looks like a UUID. Otherwise it may be a real service name (e.g. "backend")
    # and we must not hijack the request.
    if not _UUID_RE.match(dup_project_id):
        return await preview_service_proxy(project_id, dup_project_id, request, path=f"api/{path}" if path else "api")

    if dup_project_id == project_id:
        url = f"/preview/{project_id}/api/{path}" if path else f"/preview/{project_id}/api"
        if request.url.query:
            url += f"?{request.url.query}"
        return RedirectResponse(url=url, status_code=307)
    return JSONResponse({"detail": "Not Found"}, status_code=404)


@router.get("/preview/{project_id}/_test")
@router.get("/preview/{project_id}/_test/")
async def preview_api_test(project_id: str):
    deployment = _find_deployment(project_id)
    if not deployment:
        return HTMLResponse("<h1>No active deployment</h1><p>Deploy the project first.</p>", 404)

    # Prefer explicit backend service when available (fullstack), otherwise use primary.
    known = {sp.service for sp in (deployment.service_ports or [])}
    if "backend" in known:
        backend_prefix = f"/preview/{project_id}/backend"
    else:
        backend_prefix = f"/preview/{project_id}"

    return HTMLResponse(_api_test_html(project_id, backend_prefix=backend_prefix))


@router.get("/preview/{project_id}/swagger")
@router.get("/preview/{project_id}/swagger/")
async def preview_swagger_ui(project_id: str):
    deployment = _find_deployment(project_id)
    if not deployment:
        return HTMLResponse("<h1>No active deployment</h1><p>Deploy the project first.</p>", 404)
    return HTMLResponse(_swagger_ui_html(project_id))


@router.get("/preview/{project_id}/swagger.json")
async def preview_swagger_json(project_id: str):
    deployment = _find_deployment(project_id)
    if not deployment:
        return JSONResponse({"detail": "No active deployment"}, status_code=404)
    return JSONResponse(_build_openapi_doc(project_id, deployment))


# ── Per-service HTTP Proxy ───────────────────────────────────────

@router.api_route(
    "/preview/{project_id}/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def preview_service_proxy(project_id: str, service: str, request: Request, path: str = ""):
    """Reverse proxy to a specific service (frontend, backend, db)."""
    deployment = _find_deployment(project_id)
    if not deployment:
        return HTMLResponse("<h1>No active deployment</h1>", 404)

    # Check if 'service' is an actual service name or just a path segment
    known = {sp.service for sp in (deployment.service_ports or [])}
    known |= set(getattr(deployment, "compose_services", None) or [])
    rewrite_api_base: str | None = None
    frontend_base = _get_service_url(deployment, "frontend") if "frontend" in known else None
    if "backend" in known:
        rewrite_api_base = f"/preview/{project_id}/backend"

    strip_request_origin = False

    if service in known:
        base = _get_service_url(deployment, service)
        prefix = f"/preview/{project_id}/{service}"
        requested_rel_path = path
        # Only rewrite for frontend responses.
        if service != "frontend":
            rewrite_api_base = None
        if service == "backend":
            strip_request_origin = True
    else:
        # Not a service name → treat as path under the primary service.
        # For fullstack projects, many frontends call backend APIs via absolute paths
        # like /users/login (not prefixed with /backend). To keep the app usable,
        # route API-like requests to backend when a backend service exists.
        full_subpath = f"{service}/{path}" if path else service
        prefix = f"/preview/{project_id}"

        deploy_mode = (deployment.deploy_mode or "").strip().lower()
        backend_base = None
        if deploy_mode in {"backend-only", "fullstack"}:
            backend_base = _get_service_url(deployment, "backend")

        should_route_to_backend = False
        # Backend-only: keep normal routing to the primary service, but strip
        # Origin/Referer only for API-like paths. This avoids surprising behavior
        # for non-API routes while still working around strict upstream CORS.
        sub_l = full_subpath.lstrip("/").lower()
        api_like_backend_only = deploy_mode == "backend-only" and (
            sub_l == "api"
            or sub_l.startswith("api/")
            or sub_l == "uploads"
            or sub_l.startswith("uploads/")
            or sub_l == "undefined/api"
            or sub_l.startswith("undefined/api/")
            or sub_l == "undefined/uploads"
            or sub_l.startswith("undefined/uploads/")
        )
        if api_like_backend_only and not _is_probably_static_asset(full_subpath):
            should_route_to_backend = True

        if deploy_mode == "fullstack" and backend_base and not _is_probably_static_asset(full_subpath):
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                should_route_to_backend = True
            else:
                seg = full_subpath.lstrip("/").split("/", 1)[0]
                if seg and seg in _backend_path_prefixes(project_id):
                    should_route_to_backend = True

        if should_route_to_backend:
            base = backend_base or _get_service_url(deployment)
            rewrite_api_base = None
            strip_request_origin = True
        else:
            base = _get_service_url(deployment)
            # Only rewrite when the primary service is the frontend.
            if frontend_base and base != frontend_base:
                rewrite_api_base = None

        path = full_subpath
        requested_rel_path = full_subpath

    if not base:
        return HTMLResponse("<h1>No port mapping found</h1>", 502)

    proxied = await _proxy_request_to(
        project_id,
        base,
        path,
        request,
        prefix=prefix,
        rewrite_api_base=rewrite_api_base,
        strip_request_origin=strip_request_origin,
    )

    if (
        request.method.upper() in {"GET", "HEAD", "OPTIONS"}
        and proxied.status_code == 404
        and service != "backend"
    ):
        static_file = _serve_project_static_file(project_id, requested_rel_path)
        if static_file is not None:
            return static_file

    return proxied


@router.api_route(
    "/preview/{project_id}/{service}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def preview_service_proxy_no_path(project_id: str, service: str, request: Request):
    """Handle /preview/{project_id}/{service} without forcing a trailing slash.

    This matters when `service` is actually a top-level file like `landing.html`.
    Without this route, FastAPI redirects to add a trailing slash, which causes the
    upstream container to receive `/landing.html/`.
    """
    return await preview_service_proxy(project_id, service, request, path="")


# ── Proxy implementation ────────────────────────────────────────

async def _proxy_request_to(
    project_id: str,
    base_url: str,
    path: str,
    request: Optional[Request],
    *,
    prefix: str = "",
    rewrite_api_base: str | None = None,
    strip_request_origin: bool = False,
    body_override: bytes | None = None,
) -> Response:
    """Forward an HTTP request to the upstream container."""
    upstream_url = f"{base_url}/{path}" if path else f"{base_url}/"
    if request and request.query_params:
        upstream_url += f"?{request.query_params}"

    if not prefix:
        prefix = f"/preview/{project_id}"

    try:
        body = body_override if (body_override is not None) else (await request.body() if request else b"")
        headers = dict(request.headers) if request else {}
        for h in ("host", "Host"):
            headers.pop(h, None)
        for h in ("content-length", "Content-Length"):
            headers.pop(h, None)

        # Avoid upstream 304 responses: we often rewrite HTML/JS bodies and
        # cached conditional requests would bypass those rewrites.
        for h in (
            "if-none-match",
            "If-None-Match",
            "if-modified-since",
            "If-Modified-Since",
            "if-match",
            "If-Match",
            "if-unmodified-since",
            "If-Unmodified-Since",
        ):
            headers.pop(h, None)

        if strip_request_origin:
            for h in (
                "origin",
                "Origin",
                "referer",
                "Referer",
                "referrer",
                "Referrer",
                "sec-fetch-site",
                "sec-fetch-mode",
                "sec-fetch-dest",
            ):
                headers.pop(h, None)
        method = request.method if request else "GET"

        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            resp = await client.request(
                method=method,
                url=upstream_url,
                headers=headers,
                content=body,
            )

        content_type = resp.headers.get("content-type", "")
        response_body = resp.content
        did_mutate_body = False

        # Rewrite HTML links and (optionally) hardcoded localhost API origins.
        # Some static projects hardcode API calls inside JS files, so we also
        # apply the localhost-rewrite for JavaScript responses.
        should_rewrite_html = "text/html" in content_type
        should_rewrite_js = any(
            t in content_type
            for t in (
                "application/javascript",
                "text/javascript",
                "application/x-javascript",
            )
        )
        if should_rewrite_html or should_rewrite_js:
            text = response_body.decode("utf-8", errors="replace")
            if should_rewrite_html:
                text = _rewrite_html(text, prefix)
                text = _rewrite_meta_refresh_urls(text, prefix=prefix, current_path=path)
                text = _inject_preview_history_base(text, prefix=prefix)
                text = _rewrite_common_project_asset_refs(text, prefix=prefix)
                did_mutate_body = True
            if rewrite_api_base:
                text = _rewrite_localhost_api(text, api_base=rewrite_api_base)
                did_mutate_body = True
            if prefix:
                text = _rewrite_absolute_asset_paths(text, asset_base=prefix)
                text = _rewrite_common_project_asset_refs(text, prefix=prefix)
                did_mutate_body = True
            response_body = text.encode("utf-8")

        # Rewrite JS (common for static frontends calling localhost APIs)
        if (
            rewrite_api_base
            and ("javascript" in content_type or path.lower().endswith(".js"))
            and response_body
        ):
            js = response_body.decode("utf-8", errors="replace")
            js = _rewrite_localhost_api(js, api_base=rewrite_api_base)
            if prefix:
                js = _rewrite_absolute_asset_paths(js, asset_base=prefix)
                js = _rewrite_common_project_asset_refs(js, prefix=prefix)
            js = _rewrite_react_router_basename(js, prefix=prefix)
            did_mutate_body = True
            response_body = js.encode("utf-8")

        # Even when we aren't rewriting localhost APIs, we may still need to
        # set React Router basename for preview paths.
        if ("javascript" in content_type or path.lower().endswith(".js")) and response_body and prefix.startswith("/preview/"):
            js2 = response_body.decode("utf-8", errors="replace")
            js2b = _rewrite_react_router_basename(js2, prefix=prefix)
            js2b = _rewrite_common_project_asset_refs(js2b, prefix=prefix)
            if js2b != js2:
                response_body = js2b.encode("utf-8")
                did_mutate_body = True

        # Rewrite OpenAPI specs
        if "application/json" in content_type and path in ("openapi.json", "swagger.json"):
            try:
                import json
                data = json.loads(response_body)
                if "servers" in data:
                    data["servers"] = [{"url": prefix}]
                response_body = json.dumps(data).encode("utf-8")
            except Exception:
                pass

        resp_headers = dict(resp.headers)
        for h in ("transfer-encoding", "connection", "content-encoding", "content-length"):
            resp_headers.pop(h, None)

        if did_mutate_body:
            for h in (
                "etag",
                "ETag",
                "last-modified",
                "Last-Modified",
            ):
                resp_headers.pop(h, None)
            resp_headers["cache-control"] = "no-store"

        location = resp_headers.get("location") or resp_headers.get("Location")
        if location:
            target_path = ""
            if location.startswith("/"):
                target_path = location
            elif location.startswith(base_url):
                target_path = location[len(base_url):] or "/"
            else:
                m = re.match(r"https?://[^/]+(?P<path>/.*)?$", location)
                if m:
                    target_path = m.group("path") or "/"

            if target_path:
                if not target_path.startswith("/"):
                    target_path = "/" + target_path
                if prefix and target_path.startswith(prefix + "/"):
                    resp_headers["location"] = target_path
                elif prefix:
                    resp_headers["location"] = f"{prefix}{target_path}"
                else:
                    resp_headers["location"] = target_path
                resp_headers.pop("Location", None)

        response = Response(
            content=response_body,
            status_code=resp.status_code,
            headers=resp_headers,
            media_type=content_type or None,
        )

        # Persist preview context for absolute /api/* fallbacks.
        # Only set on HTML to avoid extra header spam on assets.
        if request and ("text/html" in (content_type or "")):
            response.set_cookie(
                key=_PREVIEW_PROJECT_COOKIE,
                value=project_id,
                path="/",
                samesite="lax",
            )

        return response

    except httpx.ConnectError:
        return HTMLResponse(
            "<h1>Container not reachable</h1><p>The container may still be starting.</p>", 502,
        )
    except Exception as exc:
        logger.exception("Preview proxy error: %s", exc)
        return HTMLResponse(f"<h1>Proxy Error</h1><pre>{exc}</pre>", 502)


# ── WebSocket Proxy ──────────────────────────────────────────────

@router.websocket("/preview/{project_id}/{service}/ws/{path:path}")
@router.websocket("/preview/{project_id}/{service}/ws")
@router.websocket("/preview/{project_id}/ws/{path:path}")
@router.websocket("/preview/{project_id}/ws")
async def preview_websocket(
    project_id: str,
    websocket: WebSocket,
    service: str = "",
    path: str = "",
):
    """Proxy WebSocket connections to a specific service."""
    import websockets

    deployment = _find_deployment(project_id)
    if not deployment:
        await websocket.close(code=4004, reason="No active deployment")
        return

    # Check if service is a real service or just 'ws'
    known = {sp.service for sp in (deployment.service_ports or [])}
    if service in known:
        base = _get_service_url(deployment, service)
    else:
        base = _get_service_url(deployment)

    if not base:
        await websocket.close(code=4004, reason="No upstream port")
        return

    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    upstream_url = f"{ws_base}/{path}" if path else ws_base

    await websocket.accept()

    try:
        async with websockets.connect(upstream_url) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive_text()
                        await upstream.send(data)
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        await websocket.send_text(str(message))
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())

    except Exception as exc:
        logger.warning("WebSocket proxy error: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
