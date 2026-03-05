"""Project-related data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── File tree ────────────────────────────────────────────────────

class FileNode(BaseModel):
    name: str
    path: str
    type: Literal["file", "folder"]
    size: Optional[int] = None
    children: Optional[List[FileNode]] = None


# ── Project analysis (returned by LLM or heuristic) ─────────────

PROJECT_TYPE = Literal["frontend-only", "backend-only", "fullstack", "static-html"]

# Aliases that get normalised into the canonical values above.
_TYPE_ALIASES: dict[str, str] = {
    "frontend": "frontend-only",
    "static": "frontend-only",
    "static-html": "static-html",
    "backend": "backend-only",
    "fullstack+db": "fullstack",
    "fullstack-sql": "fullstack",
    "fullstack-db": "fullstack",
}


class ProjectAnalysis(BaseModel):
    """Result of analysing a project — produced by LLM or fallback heuristic."""

    project_type: str = "fullstack"
    frontend_info: Optional[Dict[str, Any]] = None
    backend_info: Optional[Dict[str, Any]] = None
    database_info: Optional[Dict[str, Any]] = None
    tech_stack: List[str] = Field(default_factory=list)
    entry_points: Dict[str, str] = Field(default_factory=dict)
    dependencies: Dict[str, List[str]] = Field(default_factory=dict)
    recommended_ports: Dict[str, int] = Field(default_factory=dict)
    build_steps: List[str] = Field(default_factory=list)
    run_commands: Dict[str, str] = Field(default_factory=dict)
    environment_variables: List[str] = Field(default_factory=list)
    is_static_site: bool = False
    deployment_strategy: str = "docker"
    summary: str = ""

    @field_validator("project_type", mode="before")
    @classmethod
    def _normalise_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _TYPE_ALIASES.get(v.strip().lower(), v.strip().lower())
        return v

    @field_validator("dependencies", mode="before")
    @classmethod
    def _normalise_deps(cls, v: Any) -> Any:
        if v is None:
            return {}
        if not isinstance(v, dict):
            return v
        out: Dict[str, list] = {}
        for scope, deps in v.items():
            if deps is None:
                out[scope] = []
            elif isinstance(deps, list):
                out[scope] = [str(x) for x in deps if x is not None]
            elif isinstance(deps, dict):
                out[scope] = list(deps.keys())
            elif isinstance(deps, str):
                out[scope] = [deps]
            else:
                out[scope] = []
        return out


# ── Project metadata ─────────────────────────────────────────────

class ProjectMetadata(BaseModel):
    project_id: str
    name: str
    project_type: str = "unknown"
    uploaded_at: datetime = Field(default_factory=datetime.now)
    file_tree: Optional[FileNode] = None
    analysis: Optional[ProjectAnalysis] = None


# Rebuild forward refs
FileNode.model_rebuild()
