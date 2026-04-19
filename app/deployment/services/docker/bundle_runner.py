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
import socket
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
    
    # Patch docker-compose.yml to use fresh free ports to avoid allocation conflicts
    _patch_compose_ports(runtime_dir)
    
    docker_client.compose_up(str(runtime_dir), compose_project, build=False)

    compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
    services, service_ports = _parse_compose_services_and_ports(compose_text)

    primary_url = _pick_primary_url(service_ports)
    return {
        "runtime_dir": str(runtime_dir),
        "compose_project": compose_project,
        "compose_file": str(compose_file),
        "services": services,
        "service_ports": service_ports,
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


def _find_free_port() -> int:
    """Find an available host port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _patch_compose_ports(runtime_dir: Path) -> None:
    """Replace hardcoded host ports in docker-compose.yml with fresh free ports."""
    compose_path = runtime_dir / "docker-compose.yml"
    if not compose_path.exists():
        return

    content = compose_path.read_text(encoding="utf-8")
    
    # Pattern to match "host_port:container_port" in compose files
    # We look for lines like: - "33509:8000" or - 80:80
    port_pattern = re.compile(r'(\s*-\s*["\']?)(\d+):(\d+)(["\']?\s*)')
    
    def replacer(match):
        prefix = match.group(1)
        # host_port = match.group(2) # we ignore the baked-in host port
        container_port = match.group(3)
        suffix = match.group(4)
        
        new_host_port = _find_free_port()
        logger.info(f"Re-mapped container port {container_port} to host port {new_host_port}")
        return f"{prefix}{new_host_port}:{container_port}{suffix}"

    new_content = port_pattern.sub(replacer, content)
    
    if new_content != content:
        compose_path.write_text(new_content, encoding="utf-8")
        logger.info(f"Patched {compose_path.name} with fresh host ports")
