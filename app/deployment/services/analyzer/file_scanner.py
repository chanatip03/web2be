"""Scan the project directory — build file tree and sample key files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Files we always try to read for context
_PRIORITY_FILES = [
    # Package manifests (contain exact dependency versions)
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "composer.lock",
    "Gemfile",
    "Gemfile.lock",
    # Runtime version pin files (CRITICAL for choosing correct base image)
    ".nvmrc",
    ".node-version",
    ".python-version",
    ".ruby-version",
    ".tool-versions",
    # Config
    ".env.example",
    ".env.sample",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
]

_SAMPLE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java",
    ".go", ".rs", ".rb", ".php", ".html", ".css",
}

_IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", ".nuxt",
    "dist", "build", ".cache", "venv", ".venv", "env",
    ".idea", ".vscode", "target", "vendor", ".gradle",
}


def build_file_tree(
    root: Path,
    *,
    max_depth: int = 4,
    _depth: int = 0,
) -> Dict[str, Any]:
    """Recursively build a JSON-serialisable file tree."""
    if not root.exists():
        return {"name": root.name, "path": ".", "type": "folder", "children": []}

    node: Dict[str, Any] = {
        "name": root.name,
        "path": str(root.name),
        "type": "folder",
    }

    if _depth >= max_depth:
        node["children"] = [{"name": "...", "path": "...", "type": "file"}]
        return node

    children: List[Dict[str, Any]] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return node

    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env.example",):
            continue
        if entry.is_dir():
            if entry.name in _IGNORE_DIRS:
                continue
            children.append(build_file_tree(entry, max_depth=max_depth, _depth=_depth + 1))
        else:
            children.append({
                "name": entry.name,
                "path": str(entry.relative_to(root.parent)),
                "type": "file",
                "size": entry.stat().st_size,
            })

    node["children"] = children
    return node


def sample_key_files(
    root: Path,
    *,
    max_files: int = 40,
    max_chars_per_file: int = 3000,
) -> Dict[str, str]:
    """Read the most important files and return {relative_path: content}.

    Priority files are always included first, followed by sampled source files.
    """
    samples: Dict[str, str] = {}

    def _add(path: Path) -> None:
        if len(samples) >= max_files:
            return
        rel = str(path.relative_to(root))
        if rel in samples:
            return
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Compact package.json to essential fields
            if path.name == "package.json":
                text = _compact_package_json(text)
            elif len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + f"\n\n... (truncated, {len(text)} total chars)"
            samples[rel] = text
        except Exception:
            pass

    # 1. Priority files (project root + common subdirs)
    for name in _PRIORITY_FILES:
        for candidate in (root / name, root / "frontend" / name, root / "backend" / name):
            if candidate.exists():
                _add(candidate)

    # 2. Walk for source files
    for path in _walk_source_files(root):
        if len(samples) >= max_files:
            break
        _add(path)

    return samples


def _walk_source_files(root: Path) -> List[Path]:
    """Walk directory for source files, skipping ignored dirs."""
    result: List[Path] = []
    for path in root.rglob("*"):
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in _SAMPLE_EXTENSIONS:
            result.append(path)
        if len(result) > 200:
            break
    return result


def _compact_package_json(text: str) -> str:
    """Keep only deployment-relevant fields from package.json."""
    try:
        data = json.loads(text)
        compact = {
            k: data[k]
            for k in ("name", "private", "type", "scripts", "dependencies", "devDependencies", "engines")
            if k in data
        }
        # Trim dependency values to just names
        for key in ("dependencies", "devDependencies"):
            if isinstance(compact.get(key), dict):
                compact[key] = sorted(compact[key].keys())
        return json.dumps(compact, indent=2, ensure_ascii=False)
    except Exception:
        return text[:3000]
