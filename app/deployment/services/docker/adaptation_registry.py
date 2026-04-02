from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Protocol

from app.deployment.models.project import ProjectAnalysis


@dataclass
class AdaptationContext:
    project_path: Path
    analysis: Optional[ProjectAnalysis]
    mode: str


class AdaptationRule(Protocol):
    name: str

    def supports(self, mode: str) -> bool: ...

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]: ...


class AdaptationRegistry:
    def __init__(self) -> None:
        self._rules: List[AdaptationRule] = []

    def register(self, rule: AdaptationRule) -> None:
        self._rules.append(rule)

    def apply_all(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        for rule in self._rules:
            if not rule.supports(ctx.mode):
                continue
            changed.extend(rule.apply(ctx, safe_write))
        return changed


class FrontendViteBaseRule:
    name = "frontend_vite_base"

    def supports(self, mode: str) -> bool:
        return mode in {"frontend-only", "fullstack", "auto"}

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        frontend_path = str((ctx.analysis.frontend_info or {}).get("path") or "frontend").strip() if ctx.analysis else "frontend"
        roots = [ctx.project_path / frontend_path, ctx.project_path]

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for rel in ("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs"):
                file_path = root / rel
                if not file_path.exists() or not file_path.is_file():
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                new_text = re.sub(
                    r"(?m)^\s*base\s*:\s*['\"][^'\"]+['\"]\s*,?\s*$",
                    "  base: './',",
                    text,
                )
                if new_text != text and safe_write(file_path, new_text):
                    changed.append(str(file_path.relative_to(ctx.project_path)))
        return changed


class FrontendBrowserRouterRule:
    name = "frontend_router_basename"

    def supports(self, mode: str) -> bool:
        return mode in {"frontend-only", "fullstack", "auto"}

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        frontend_path = str((ctx.analysis.frontend_info or {}).get("path") or "frontend").strip() if ctx.analysis else "frontend"
        roots = [ctx.project_path / frontend_path, ctx.project_path]

        app_candidates: List[Path] = []
        for root in roots:
            src_dir = root / "src"
            if not src_dir.exists() or not src_dir.is_dir():
                continue
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
            if new_text != text and safe_write(file_path, new_text):
                changed.append(str(file_path.relative_to(ctx.project_path)))
        return changed


class NodeMysqlEnvRule:
    name = "node_mysql_env_aliases"

    def supports(self, mode: str) -> bool:
        return mode in {"backend-only", "fullstack", "auto"}

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        backend_path = str((ctx.analysis.backend_info or {}).get("path") or "backend").strip() if ctx.analysis else "backend"
        roots = [ctx.project_path / backend_path, ctx.project_path]

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

                    if new_text != text and safe_write(file_path, new_text):
                        changed.append(str(file_path.relative_to(ctx.project_path)))

        return changed


class FrontendApiBaseRule:
    name = "frontend_api_base_preview"

    def supports(self, mode: str) -> bool:
        return mode in {"frontend-only", "fullstack", "auto"}

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        frontend_path = str((ctx.analysis.frontend_info or {}).get("path") or "frontend").strip() if ctx.analysis else "frontend"
        roots = [ctx.project_path / frontend_path, ctx.project_path]

        preview_expr = "(typeof window !== 'undefined' && window.location.pathname.startsWith('/preview/') ? '/preview/' + window.location.pathname.split('/')[2] : '')"

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for rel in ("src/config.ts", "src/config.js", "src/constants.ts", "src/constants.js", "config.ts", "config.js"):
                file_path = root / rel
                if not file_path.exists() or not file_path.is_file():
                    continue
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                new_text = text
                new_text = re.sub(
                    r"API_URL\s*:\s*['\"]https?://(?:localhost|127\.0\.0\.1):\d+['\"]",
                    f"API_URL: {preview_expr}",
                    new_text,
                )
                new_text = re.sub(
                    r"BASE_URL\s*:\s*['\"]https?://(?:localhost|127\.0\.0\.1):\d+['\"]",
                    f"BASE_URL: {preview_expr}",
                    new_text,
                )
                if new_text != text and safe_write(file_path, new_text):
                    changed.append(str(file_path.relative_to(ctx.project_path)))
        return changed


class FrontendEnvApiReferenceRule:
    name = "frontend_env_api_reference_preview"

    def supports(self, mode: str) -> bool:
        return mode in {"frontend-only", "fullstack", "auto"}

    def apply(self, ctx: AdaptationContext, safe_write: Callable[[Path, str], bool]) -> List[str]:
        changed: List[str] = []
        frontend_path = str((ctx.analysis.frontend_info or {}).get("path") or "frontend").strip() if ctx.analysis else "frontend"
        roots = [ctx.project_path / frontend_path, ctx.project_path]

        preview_expr = "(typeof window !== 'undefined' && window.location.pathname.startsWith('/preview/') ? '/preview/' + window.location.pathname.split('/')[2] : '')"
        vite_expr = f"({preview_expr} || import.meta.env['VITE_API_URL'] || '')"
        react_expr = f"({preview_expr} || process.env['REACT_APP_API_URL'] || '')"

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for pattern in ("*.ts", "*.tsx", "*.js", "*.jsx"):
                for file_path in root.rglob(pattern):
                    if any(part in {"node_modules", "dist", "build", "out"} for part in file_path.parts):
                        continue
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                    if "import.meta.env.VITE_API_URL" not in text and "process.env.REACT_APP_API_URL" not in text:
                        continue

                    new_text = text.replace("import.meta.env.VITE_API_URL", vite_expr)
                    new_text = new_text.replace("process.env.REACT_APP_API_URL", react_expr)

                    if new_text != text and safe_write(file_path, new_text):
                        changed.append(str(file_path.relative_to(ctx.project_path)))
        return changed


def create_default_registry() -> AdaptationRegistry:
    registry = AdaptationRegistry()
    registry.register(FrontendViteBaseRule())
    registry.register(FrontendBrowserRouterRule())
    registry.register(FrontendApiBaseRule())
    registry.register(FrontendEnvApiReferenceRule())
    registry.register(NodeMysqlEnvRule())
    return registry
