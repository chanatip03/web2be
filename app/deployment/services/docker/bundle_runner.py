"""Run deployments directly from a portable bundle (.tar.gz).

Bundle layout (created by services.docker.bundler):
  images.tar
  docker-compose.yml
  .env
  README.md
  (optional) .deploy/* and seed.sql referenced by compose
"""

from __future__ import annotations

import logging
import re
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.deployment.core.exceptions import DockerError
from app.deployment.services.docker.client import docker_client

logger = logging.getLogger(__name__)


def extract_bundle(*, bundle_path: Path, target_dir: Path, overwrite: bool = True) -> None:
    """Safely extract a .tar.gz bundle into *target_dir*."""
    if overwrite and target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(str(bundle_path), "r:gz") as tar:
        _safe_extractall(tar, target_dir)


def run_from_bundle(
    *,
    bundle_path: Path,
    runtime_dir: Path,
    compose_project: str,
    remove_existing: bool = True,
) -> Dict[str, Any]:
    """Extract bundle, docker-load images, compose up, and return runtime metadata."""
    extract_bundle(bundle_path=bundle_path, target_dir=runtime_dir, overwrite=True)

    images_tar = runtime_dir / "images.tar"
    compose_file = runtime_dir / "docker-compose.yml"
    if not images_tar.exists():
        raise FileNotFoundError("Bundle is missing images.tar")
    if not compose_file.exists():
        raise FileNotFoundError("Bundle is missing docker-compose.yml")

    logger.info("Bundle run: docker load %s", images_tar)
    docker_client.load_images_tar(str(images_tar))

    if remove_existing:
        try:
            docker_client.compose_down(str(runtime_dir), compose_project, remove_volumes=True)
        except Exception:
            pass

    logger.info("Bundle run: docker compose up -d (%s)", compose_project)
    docker_client.compose_up(str(runtime_dir), compose_project, build=False)

    compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
    services, service_ports = _parse_compose_services_and_ports(compose_text)
    image_refs = _parse_compose_image_refs(compose_text)

    primary_url = _pick_primary_url(service_ports)
    return {
        "runtime_dir": str(runtime_dir),
        "compose_project": compose_project,
        "compose_file": str(compose_file),
        "services": services,
        "service_ports": service_ports,
        "image_refs": image_refs,
        "primary_url": primary_url,
    }


def _safe_extractall(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Prevent path traversal when extracting tarballs."""
    target_dir_resolved = target_dir.resolve()
    for member in tar.getmembers():
        member_path = target_dir / member.name
        try:
            member_resolved = member_path.resolve()
        except Exception:
            continue
        if not str(member_resolved).startswith(str(target_dir_resolved)):
            raise ValueError(f"Unsafe path in bundle: {member.name}")
    tar.extractall(str(target_dir))


def _parse_compose_services_and_ports(compose_text: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Best-effort parser for docker-compose.yml produced by our generator."""
    services: List[str] = []
    service_ports: List[Dict[str, Any]] = []

    service_header_re = re.compile(r"^\s{2}([a-zA-Z0-9_-]+):\s*$")
    port_re = re.compile(r"^\s*-\s*\"?(\d+):(\d+)\"?\s*$")

    current_service: Optional[str] = None
    in_ports = False

    for line in compose_text.splitlines():
        header = service_header_re.match(line)
        if header:
            current_service = header.group(1)
            services.append(current_service)
            in_ports = False
            continue

        if current_service is None:
            continue

        stripped = line.strip()
        if stripped == "ports:":
            in_ports = True
            continue
        if in_ports:
            m = port_re.match(line)
            if m:
                host_port = int(m.group(1))
                container_port = int(m.group(2))
                service_ports.append(
                    {
                        "service": current_service,
                        "container_port": container_port,
                        "host_port": host_port,
                        "url": f"http://localhost:{host_port}",
                    }
                )
                continue
            # End ports list when indentation changes / next key begins
            if stripped and not stripped.startswith("-"):
                in_ports = False

    return services, service_ports


def _pick_primary_url(service_ports: List[Dict[str, Any]]) -> Optional[str]:
    by_service: Dict[str, str] = {}
    for sp in service_ports:
        if sp.get("url") and sp.get("service"):
            by_service[str(sp["service"])] = str(sp["url"])
    for pref in ("frontend", "backend", "app"):
        if pref in by_service:
            return by_service[pref]
    return next(iter(by_service.values()), None)


def _parse_compose_image_refs(compose_text: str) -> List[str]:
    image_refs: List[str] = []
    image_re = re.compile(r'^\s*image:\s*["\']?([^"\'#]+)')

    for line in compose_text.splitlines():
        match = image_re.match(line)
        if not match:
            continue
        image_ref = match.group(1).strip()
        if image_ref and image_ref not in image_refs:
            image_refs.append(image_ref)

    return image_refs
