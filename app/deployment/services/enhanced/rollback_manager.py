"""Rollback manager — version snapshots and restore."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings

logger = logging.getLogger(__name__)


class RollbackManager:
    """Save deployment snapshots and roll back to previous versions."""

    def __init__(self):
        self._versions_dir = Path(settings.deployments_dir) / ".versions"
        self._versions_dir.mkdir(parents=True, exist_ok=True)

    def save_version(
        self,
        deployment_id: str,
        *,
        dockerfile: str = "",
        compose: str = "",
        build_spec: Optional[Dict[str, Any]] = None,
        image_tag: str = "",
    ) -> str:
        """Save current state as a version snapshot. Returns version_id."""
        version_id = f"v-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        version_dir = self._versions_dir / deployment_id / version_id
        version_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "version_id": version_id,
            "deployment_id": deployment_id,
            "created_at": datetime.now().isoformat(),
            "image_tag": image_tag,
        }

        # Save artifacts
        if dockerfile:
            (version_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        if compose:
            (version_dir / "docker-compose.yml").write_text(compose, encoding="utf-8")
        if build_spec:
            (version_dir / "build_spec.json").write_text(
                json.dumps(build_spec, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        (version_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        logger.info("Saved version %s for %s", version_id, deployment_id)
        return version_id

    def list_versions(self, deployment_id: str) -> List[Dict[str, Any]]:
        """List all versions for a deployment."""
        dep_dir = self._versions_dir / deployment_id
        if not dep_dir.exists():
            return []

        versions = []
        for vdir in sorted(dep_dir.iterdir(), reverse=True):
            if not vdir.is_dir():
                continue
            manifest_path = vdir / "manifest.json"
            if manifest_path.exists():
                try:
                    versions.append(json.loads(manifest_path.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return versions

    def get_version(self, deployment_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific version's artifacts."""
        version_dir = self._versions_dir / deployment_id / version_id
        if not version_dir.exists():
            return None

        result: Dict[str, Any] = {"version_id": version_id}

        for name in ("Dockerfile", "docker-compose.yml"):
            path = version_dir / name
            if path.exists():
                result[name.lower().replace("-", "_").replace(".", "_")] = path.read_text(encoding="utf-8")

        spec_path = version_dir / "build_spec.json"
        if spec_path.exists():
            try:
                result["build_spec"] = json.loads(spec_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        manifest_path = version_dir / "manifest.json"
        if manifest_path.exists():
            try:
                result["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        return result

    def get_latest_version(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent version."""
        versions = self.list_versions(deployment_id)
        if not versions:
            return None
        return self.get_version(deployment_id, versions[0]["version_id"])


rollback_manager = RollbackManager()
