"""Deployment-related data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


DEPLOY_STATUS = Literal[
    "analyzing",
    "building",
    "deploying",
    "running",
    "success",
    "stopped",
    "error",
]


class DeploymentConfig(BaseModel):
    """Parameters needed to build and run a Docker deployment."""

    deployment_id: str
    project_id: str
    dockerfile_content: str = ""
    compose_content: Optional[str] = None
    build_context: str = "."
    ports: Dict[str, int] = Field(default_factory=dict)
    environment: Dict[str, str] = Field(default_factory=dict)
    build_spec: Optional[Dict[str, Any]] = None


class ServicePortMapping(BaseModel):
    """Tracks a single service's port mapping."""
    service: str              # "frontend", "backend", "db"
    container_port: int       # port inside container
    host_port: int            # port exposed to host
    url: Optional[str] = None # http://localhost:{host_port}


class DeploymentStatus(BaseModel):
    """Tracks the lifecycle of a single deployment."""

    deployment_id: str
    project_id: str
    project_name: str = ""
    deploy_mode: str = "auto"  # frontend-only | backend-only | fullstack
    status: str = "analyzing"
    current_step: int = 1
    total_steps: int = 4
    preview_url: Optional[str] = None
    api_url: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.now)

    # Docker state
    container_id: Optional[str] = None
    container_state: Optional[str] = None  # running | stopped
    host_port: Optional[int] = None
    extra_ports: Optional[List[Dict[str, Any]]] = None
    image_tag: Optional[str] = None
    image_tags: Optional[Dict[str, str]] = None  # {"frontend": "tag", "backend": "tag"}

    # Per-service port map — key for multi-project support
    service_ports: Optional[List[ServicePortMapping]] = None

    # Compose state
    compose_file_path: Optional[str] = None
    compose_project: Optional[str] = None
    compose_services: Optional[List[str]] = None

    # Logs captured during deployment
    build_logs: Optional[str] = None

    def get_service_url(self, service: str) -> Optional[str]:
        """Get the host URL for a specific service."""
        if self.service_ports:
            for sp in self.service_ports:
                if sp.service == service:
                    return sp.url
        return None

    def get_primary_url(self) -> Optional[str]:
        """Get the primary preview URL (frontend first, then backend)."""
        if self.preview_url:
            return self.preview_url
        for pref in ("frontend", "backend", "app"):
            url = self.get_service_url(pref)
            if url:
                return url
        if self.host_port:
            return f"http://localhost:{self.host_port}"
        return None
