"""AST-based code parser — extract UI elements, API endpoints, and components.

Supports: FastAPI, Flask, Express/Fastify (JS/TS), Spring (Java),
React/Vue (JSX/TSX), HTML. Ported from v1 with sync I/O for v3 consistency.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class UIElement:
    type: str       # button | input | form | link
    name: str
    id: Optional[str] = None
    className: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class APIEndpoint:
    method: str     # GET | POST | PUT | DELETE | PATCH
    path: str
    function_name: str
    parameters: List[str] = field(default_factory=list)
    body_fields: List[str] = field(default_factory=list)
    query_fields: List[str] = field(default_factory=list)
    path_params: List[str] = field(default_factory=list)
    file_path: str = ""
    line_number: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    name: str
    props: List[str] = field(default_factory=list)
    file_path: str = ""
    exports: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_IGNORE_DIRS = {
    "node_modules", "venv", "env", "__pycache__",
    ".git", "dist", "build", ".next", "coverage", ".venv",
}


class CodeParser:
    """Parse project source code and extract endpoints, UI elements, components."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self.ui_elements: List[UIElement] = []
        self.api_endpoints: List[APIEndpoint] = []
        self.components: List[Component] = []
        self.routes: List[str] = []
        self.route_prefix_map: Dict[str, str] = {}

    # ──────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────

    def parse_project(self) -> Dict[str, Any]:
        """Parse the entire project directory and return summary."""

        # JS/TS/JSX/TSX/Vue
        for ext in (".js", ".jsx", ".ts", ".tsx", ".vue"):
            for fp in self.project_path.rglob(f"*{ext}"):
                if self._should_ignore(fp):
                    continue
                self._parse_frontend_file(fp)

        # Python
        for fp in self.project_path.rglob("*.py"):
            if self._should_ignore(fp):
                continue
            self._parse_python_file(fp)

        self._collect_express_route_prefixes()
        self._apply_route_prefixes()

        # Java
        for fp in self.project_path.rglob("*.java"):
            if self._should_ignore(fp):
                continue
            self._parse_java_file(fp)

        # HTML
        for fp in self.project_path.rglob("*.html"):
            if self._should_ignore(fp):
                continue
            self._parse_html_file(fp)

        # Cap to avoid huge payloads
        ui_cap, ep_cap, comp_cap, route_cap = 200, 250, 250, 250
        ui = self.ui_elements[:ui_cap]
        eps = self.api_endpoints[:ep_cap]
        comps = self.components[:comp_cap]
        routes = self.routes[:route_cap]

        return {
            "ui_elements": [e.to_dict() for e in ui],
            "api_endpoints": [e.to_dict() for e in eps],
            "components": [c.to_dict() for c in comps],
            "routes": routes,
            "summary": {
                "total_ui_elements": len(self.ui_elements),
                "total_buttons": sum(1 for e in self.ui_elements if e.type == "button"),
                "total_inputs": sum(1 for e in self.ui_elements if e.type == "input"),
                "total_forms": sum(1 for e in self.ui_elements if e.type == "form"),
                "total_api_endpoints": len(self.api_endpoints),
                "total_components": len(self.components),
                "total_routes": len(self.routes),
                "capped_endpoints": max(0, len(self.api_endpoints) - ep_cap),
            },
        }

    # ──────────────────────────────────────────────────────────────
    # Route prefix resolution (Express app.use("/prefix", router))
    # ──────────────────────────────────────────────────────────────

    def _collect_express_route_prefixes(self) -> None:
        proj_root = self.project_path.resolve()
        req_pat = re.compile(
            r"(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*require\(['\"]([^'\"]+)['\"]\)"
        )
        imp_pat = re.compile(
            r"import\s+([A-Za-z_]\w*)\s+from\s+['\"]([^'\"]+)['\"]"
        )
        use_pat = re.compile(
            r"app\.use\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_]\w*)\s*\)"
        )
        for fp in self.project_path.rglob("*"):
            if fp.suffix not in {".js", ".ts", ".jsx", ".tsx"}:
                continue
            if self._should_ignore(fp):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            var_map: Dict[str, str] = {}
            for m in req_pat.finditer(text):
                var_map[m.group(1)] = m.group(2)
            for m in imp_pat.finditer(text):
                var_map[m.group(1)] = m.group(2)
            for m in use_pat.finditer(text):
                prefix = m.group(1)
                var = m.group(2)
                mod = var_map.get(var)
                if not mod:
                    continue
                resolved = self._resolve_module_file(fp.parent, mod)
                if not resolved:
                    continue
                try:
                    key = str(resolved.relative_to(proj_root))
                    self.route_prefix_map[key] = prefix
                except ValueError:
                    pass

    def _resolve_module_file(self, base: Path, module_path: str) -> Optional[Path]:
        if not module_path.startswith("."):
            return None
        candidate = (base / module_path).resolve()
        if candidate.is_dir():
            for ext in (".js", ".ts", ".jsx", ".tsx"):
                idx = candidate / f"index{ext}"
                if idx.exists():
                    return idx
        if candidate.exists():
            return candidate
        for ext in (".js", ".ts", ".jsx", ".tsx"):
            ep = candidate.with_suffix(ext)
            if ep.exists():
                return ep
        return None

    def _apply_route_prefixes(self) -> None:
        if not self.route_prefix_map:
            return
        for ep in self.api_endpoints:
            prefix = self.route_prefix_map.get(ep.file_path)
            if not prefix:
                for key, val in self.route_prefix_map.items():
                    if ep.file_path.endswith(key):
                        prefix = val
                        break
            if not prefix:
                continue
            prefix = prefix if prefix.startswith("/") else f"/{prefix}"
            path = ep.path if ep.path.startswith("/") else f"/{ep.path}"
            ep.path = f"{prefix.rstrip('/')}{path}"

    # ──────────────────────────────────────────────────────────────
    # Python file parser
    # ──────────────────────────────────────────────────────────────

    def _parse_python_file(self, fp: Path) -> None:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            relative = str(fp.relative_to(self.project_path))
            tree = ast.parse(content)
            self._extract_fastapi_routes(tree, relative, content)
            self._extract_flask_routes(tree, relative, content)
        except Exception:
            pass

    def _extract_fastapi_routes(self, tree: ast.AST, file_path: str, content: str) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    ep = self._parse_fastapi_decorator(dec, node, file_path)
                    if ep:
                        self.api_endpoints.append(ep)

    def _parse_fastapi_decorator(
        self,
        decorator: ast.AST,
        func: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        file_path: str,
    ) -> Optional[APIEndpoint]:
        try:
            if not isinstance(decorator, ast.Call):
                return None
            if not isinstance(decorator.func, ast.Attribute):
                return None
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                return None
            if not decorator.args:
                return None
            first = decorator.args[0]
            path = (
                first.value if isinstance(first, ast.Constant)
                else (first.s if hasattr(ast, "Str") and isinstance(first, ast.Str) else None)
            )
            if not path:
                return None

            path_params = re.findall(r"\{([^}]+)\}", path)
            defaults: Dict[str, ast.AST] = {}
            if func.args.defaults:
                for arg, dft in zip(func.args.args[-len(func.args.defaults):], func.args.defaults):
                    defaults[arg.arg] = dft
            for arg, dft in zip(func.args.kwonlyargs, func.args.kw_defaults or []):
                if dft is not None:
                    defaults[arg.arg] = dft

            body_fields: set = set()
            query_fields: set = set()
            for arg in list(func.args.args) + list(func.args.kwonlyargs or []):
                name = arg.arg
                if name in {"self", "cls", "request", "response", "background_tasks"}:
                    continue
                if name in path_params:
                    continue
                cls = self._classify_fastapi_param(name, arg.annotation, defaults.get(name), method)
                if cls == "query":
                    query_fields.add(name)
                elif cls == "body":
                    body_fields.add(name)

            return APIEndpoint(
                method=method,
                path=path,
                function_name=func.name,
                parameters=sorted(query_fields),
                body_fields=sorted(body_fields),
                query_fields=sorted(query_fields),
                path_params=sorted(path_params),
                file_path=file_path,
                line_number=func.lineno,
            )
        except Exception:
            return None

    def _classify_fastapi_param(
        self,
        name: str,
        annotation: Optional[ast.AST],
        default: Optional[ast.AST],
        method: str,
    ) -> str:
        def _call_name(node: ast.AST) -> Optional[str]:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return node.attr
            return None

        if default is not None and isinstance(default, ast.Call):
            cn = _call_name(default.func)
            if cn in {"Path"}:
                return "path"
            if cn in {"Query", "Header", "Cookie", "Depends"}:
                return "query"
            if cn in {"Body", "Form", "File"}:
                return "body"

        if annotation is not None:
            if isinstance(annotation, ast.Name) and annotation.id in {"Request", "Response", "UploadFile"}:
                return "ignore" if annotation.id != "UploadFile" else "body"
            if isinstance(annotation, ast.Attribute) and annotation.attr in {"Request", "Response"}:
                return "ignore"

        return "query" if method in {"GET", "DELETE"} else "body"

    def _extract_flask_routes(self, tree: ast.AST, file_path: str, content: str) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    ep = self._parse_flask_decorator(dec, node, file_path)
                    if ep:
                        self.api_endpoints.append(ep)

    def _parse_flask_decorator(
        self,
        decorator: ast.AST,
        func: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        file_path: str,
    ) -> Optional[APIEndpoint]:
        try:
            if not isinstance(decorator, ast.Call):
                return None
            if not isinstance(decorator.func, ast.Attribute) or decorator.func.attr != "route":
                return None
            if not decorator.args:
                return None
            first = decorator.args[0]
            path = (
                first.value if isinstance(first, ast.Constant)
                else (first.s if hasattr(ast, "Str") and isinstance(first, ast.Str) else None)
            )
            if not path:
                return None
            path_params = re.findall(r"<(?:[^:>]+:)?([^>]+)>", path)
            methods = ["GET"]
            for kw in decorator.keywords:
                if kw.arg == "methods" and isinstance(kw.value, ast.List):
                    methods = [
                        (e.value if isinstance(e, ast.Constant) else (e.s if hasattr(ast, "Str") and isinstance(e, ast.Str) else "GET"))
                        for e in kw.value.elts
                    ]
            return APIEndpoint(
                method=methods[0],
                path=path,
                function_name=func.name,
                parameters=[],
                body_fields=[],
                query_fields=[],
                path_params=sorted(set(path_params)),
                file_path=file_path,
                line_number=func.lineno,
            )
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # JavaScript / TypeScript
    # ──────────────────────────────────────────────────────────────

    def _parse_frontend_file(self, fp: Path) -> None:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            relative = str(fp.relative_to(self.project_path))
            self._extract_components(content, relative)
            self._extract_jsx_elements(content, relative)
            self._extract_react_routes(content)
            self._extract_vue_routes(content)
            self._extract_js_api_routes(content, relative)
        except Exception:
            pass

    def _extract_js_api_routes(self, content: str, file_path: str) -> None:
        patterns = [
            r"(?:app|router|fastify)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)[\"']",
            r"@(?:Get|Post|Put|Delete|Patch)\s*\(\s*[\"']([^\"']*)[\"']\s*\)",
        ]
        matches = []
        for pat in patterns:
            for m in re.finditer(pat, content):
                if pat.startswith("@"):
                    path = m.group(1) or "/"
                    raw = m.group(0)
                    method = (
                        "GET" if "Get" in raw else "POST" if "Post" in raw else
                        "PUT" if "Put" in raw else "DELETE" if "Delete" in raw else "PATCH"
                    )
                else:
                    method = m.group(1).upper()
                    path = m.group(2)
                matches.append({"start": m.start(), "end": m.end(), "method": method, "path": path})
        matches.sort(key=lambda x: x["start"])
        for idx, item in enumerate(matches):
            next_start = matches[idx + 1]["start"] if idx + 1 < len(matches) else len(content)
            snippet = content[item["end"]: next_start][:4000]
            body_fields: set = set()
            query_fields: set = set()
            path_params: set = set()
            for f in re.findall(r"req\.body\.?([A-Za-z0-9_]+)", snippet):
                body_fields.add(f)
            for f in re.findall(r"req\.query\.?([A-Za-z0-9_]+)", snippet):
                query_fields.add(f)
            for f in re.findall(r"req\.params\.?([A-Za-z0-9_]+)", snippet):
                path_params.add(f)
            for f in re.findall(r":([A-Za-z0-9_]+)", item["path"]):
                path_params.add(f)
            line_number = content.count("\n", 0, item["start"]) + 1
            self.api_endpoints.append(APIEndpoint(
                method=item["method"],
                path=item["path"],
                function_name=f"{item['method'].lower()}_{item['path'].strip('/').replace('/', '_') or 'root'}",
                parameters=sorted(query_fields),
                body_fields=sorted(body_fields),
                query_fields=sorted(query_fields),
                path_params=sorted(path_params),
                file_path=file_path,
                line_number=line_number,
            ))

    # ──────────────────────────────────────────────────────────────
    # Java / Spring
    # ──────────────────────────────────────────────────────────────

    def _parse_java_file(self, fp: Path) -> None:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            relative = str(fp.relative_to(self.project_path))
            self._extract_spring_routes(content, relative)
        except Exception:
            pass

    def _extract_spring_routes(self, content: str, file_path: str) -> None:
        class_idx = content.find("class ")
        class_base = self._extract_java_mapping_path(content[:class_idx]) if class_idx != -1 else ""
        pat = re.compile(
            r"@(?P<ann>GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)"
            r"(?:\s*\((?P<args>[^)]*)\))?",
            re.MULTILINE,
        )
        for m in pat.finditer(content):
            if class_idx != -1 and m.start() < class_idx:
                continue
            method = self._spring_method(m.group("ann"), m.group("args") or "")
            path = self._join_paths(class_base, self._extract_java_mapping_path(m.group("args") or ""))
            snippet = content[m.end():]
            func_name = self._extract_java_method_name(snippet)
            if not func_name:
                continue
            path_params = set(re.findall(r"\{([^}]+)\}", path))
            line_number = content.count("\n", 0, m.start()) + 1
            self.api_endpoints.append(APIEndpoint(
                method=method,
                path=path or "/",
                function_name=func_name,
                parameters=[],
                body_fields=[],
                query_fields=[],
                path_params=sorted(path_params),
                file_path=file_path,
                line_number=line_number,
            ))

    def _extract_java_mapping_path(self, args: str) -> str:
        if not args:
            return ""
        pm = re.search(r'(?:value|path)\s*=\s*(\{[^}]+\}|\"[^\"]+\"|\'[^\']+\')', args)
        if pm:
            return self._first_string_literal(pm.group(1))
        lm = re.search(r'\"([^\"]+)\"|\'([^\']+)\'', args)
        if lm:
            return lm.group(1) or lm.group(2) or ""
        return ""

    def _first_string_literal(self, value: str) -> str:
        m = re.search(r'\"([^\"]+)\"|\'([^\']+)\'', value)
        return (m.group(1) or m.group(2) or "") if m else value.strip().strip('"\'')

    def _spring_method(self, annotation: str, args: str) -> str:
        mapping = {
            "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
            "DeleteMapping": "DELETE", "PatchMapping": "PATCH",
        }
        if annotation in mapping:
            return mapping[annotation]
        m = re.search(r"RequestMethod\.(GET|POST|PUT|DELETE|PATCH)", args)
        return m.group(1) if m else "GET"

    def _extract_java_method_name(self, content_after: str) -> Optional[str]:
        m = re.search(r"(?:public|protected|private)?\s+[\w<>\[\],\s]+\s+(\w+)\s*\(", content_after)
        return m.group(1) if m else None

    def _join_paths(self, base: str, path: str) -> str:
        if not base:
            return path or ""
        if not path:
            return base
        base = base if base.startswith("/") else f"/{base}"
        path = path if path.startswith("/") else f"/{path}"
        return f"{base.rstrip('/')}{path}"

    # ──────────────────────────────────────────────────────────────
    # HTML & JSX elements
    # ──────────────────────────────────────────────────────────────

    def _parse_html_file(self, fp: Path) -> None:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            relative = str(fp.relative_to(self.project_path))
            self._extract_html_buttons(content, relative)
            self._extract_html_forms(content, relative)
            self._extract_html_inputs(content, relative)
            self._extract_html_links(content, relative)
        except Exception:
            pass

    def _extract_jsx_elements(self, content: str, file_path: str) -> None:
        # Buttons
        for m in re.finditer(r"<button([^>]*)>(.*?)</button>", content, re.DOTALL):
            a = self._all_attrs(m.group(1))
            text = re.sub(r"\{[^}]+\}", "", m.group(2)).strip()
            label = self._label(text, a.get("aria-label"), a.get("data-testid"), a.get("id"))
            self.ui_elements.append(UIElement("button", label or "Button", a.get("id"), a.get("className") or a.get("class"), a, file_path, content.count("\n", 0, m.start()) + 1))
        # Inputs
        for m in re.finditer(r"<input([^/>]*)/?>", content):
            a = self._all_attrs(m.group(1))
            label = self._label(a.get("name"), a.get("placeholder"), a.get("aria-label"), a.get("id"))
            self.ui_elements.append(UIElement("input", label or "Input", a.get("id"), a.get("className") or a.get("class"), a, file_path, content.count("\n", 0, m.start()) + 1))
        # Forms
        for m in re.finditer(r"<form([^>]*)>", content):
            a = self._all_attrs(m.group(1))
            label = self._label(a.get("id"), a.get("name"), a.get("data-testid"))
            self.ui_elements.append(UIElement("form", label or "Form", a.get("id"), a.get("className") or a.get("class"), a, file_path, content.count("\n", 0, m.start()) + 1))
        # Links
        for m in re.finditer(r"<(?:a|Link)([^>]*)>(.*?)</(?:a|Link)>", content, re.DOTALL):
            a = self._all_attrs(m.group(1))
            text = re.sub(r"\{[^}]+\}", "", m.group(2)).strip()
            label = self._label(text, a.get("aria-label"), a.get("href"))
            self.ui_elements.append(UIElement("link", label or "Link", a.get("id"), a.get("className") or a.get("class"), a, file_path, content.count("\n", 0, m.start()) + 1))
        # Select
        for m in re.finditer(r"<select([^>]*)>", content):
            a = self._all_attrs(m.group(1))
            a.setdefault("tag", "select")
            label = self._label(a.get("name"), a.get("aria-label"), a.get("id"))
            self.ui_elements.append(UIElement("input", label or "Select", a.get("id"), a.get("className") or a.get("class"), a, file_path, content.count("\n", 0, m.start()) + 1))

    def _extract_html_buttons(self, content: str, fp: str) -> None:
        for m in re.finditer(r"<button([^>]*)>(.*?)</button>", content, re.DOTALL):
            a = self._all_attrs(m.group(1))
            text = m.group(2).strip()
            label = self._label(text, a.get("aria-label"), a.get("id"))
            self.ui_elements.append(UIElement("button", label or "Button", a.get("id"), a.get("class"), a, fp, content.count("\n", 0, m.start()) + 1))

    def _extract_html_forms(self, content: str, fp: str) -> None:
        for m in re.finditer(r"<form([^>]*)>", content):
            a = self._all_attrs(m.group(1))
            label = self._label(a.get("id"), a.get("name"))
            self.ui_elements.append(UIElement("form", label or "Form", a.get("id"), a.get("class"), a, fp, content.count("\n", 0, m.start()) + 1))

    def _extract_html_inputs(self, content: str, fp: str) -> None:
        for m in re.finditer(r"<input([^>]*/?>)", content):
            a = self._all_attrs(m.group(1))
            label = self._label(a.get("name"), a.get("placeholder"), a.get("id"))
            self.ui_elements.append(UIElement("input", label or "Input", a.get("id"), a.get("class"), a, fp, content.count("\n", 0, m.start()) + 1))

    def _extract_html_links(self, content: str, fp: str) -> None:
        for m in re.finditer(r"<a([^>]*)>(.*?)</a>", content, re.DOTALL):
            a = self._all_attrs(m.group(1))
            text = re.sub(r"\{[^}]+\}", "", m.group(2)).strip()
            label = self._label(text, a.get("href"), a.get("aria-label"))
            self.ui_elements.append(UIElement("link", label or "Link", a.get("id"), a.get("class"), a, fp, content.count("\n", 0, m.start()) + 1))

    # ──────────────────────────────────────────────────────────────
    # Components
    # ──────────────────────────────────────────────────────────────

    def _extract_components(self, content: str, file_path: str) -> None:
        patterns = [
            r"(?:export\s+)?(?:default\s+)?function\s+([A-Z]\w+)\s*\(",
            r"(?:export\s+)?(?:default\s+)?const\s+([A-Z]\w+)\s*=\s*\(",
            r"class\s+([A-Z]\w+)\s+extends\s+(?:React\.)?Component",
        ]
        for pat in patterns:
            for m in re.finditer(pat, content):
                name = m.group(1)
                self.components.append(Component(
                    name=name,
                    props=self._extract_props(content, name),
                    file_path=file_path,
                    exports="export" in m.group(0),
                ))

    def _extract_props(self, content: str, component_name: str) -> List[str]:
        pat = rf"{component_name}\s*\(\s*\{{\s*([^}}]+)\s*\}}\s*\)"
        m = re.search(pat, content)
        if m:
            return [p.strip().split(":")[0].strip() for p in m.group(1).split(",") if p.strip()]
        return []

    # ──────────────────────────────────────────────────────────────
    # Router routes
    # ──────────────────────────────────────────────────────────────

    def _extract_react_routes(self, content: str) -> None:
        for m in re.finditer(r'<Route\s+path=["\']([^"\']+)["\']', content):
            r = m.group(1)
            if r not in self.routes:
                self.routes.append(r)

    def _extract_vue_routes(self, content: str) -> None:
        for m in re.finditer(r"path:\s*[\"']([^\"']+)[\"']", content):
            r = m.group(1)
            if r not in self.routes:
                self.routes.append(r)

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def _all_attrs(self, attrs: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for m in re.finditer(r'([\w:-]+)=["\']([^"\']+)["\']', attrs):
            result[m.group(1)] = m.group(2)
        return result

    def _label(self, *values: Optional[str]) -> str:
        for v in values:
            if v:
                s = str(v).strip()
                if s:
                    return s
        return ""

    def _should_ignore(self, path: Path) -> bool:
        parts = set(path.parts)
        return bool(parts & _IGNORE_DIRS)


def parse_project_code(project_path: str | Path) -> Dict[str, Any]:
    """Entry point: parse a project directory and return analysis results."""
    return CodeParser(project_path).parse_project()
