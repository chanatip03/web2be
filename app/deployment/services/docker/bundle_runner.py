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

    # 3. Final safety: rewrite any fixed host ports to 0 (dynamic) to avoid conflicts 
    # and repair suspicious container ports (e.g. if they look like host ports > 1024).
    compose_text = compose_file.read_text(encoding="utf-8", errors="replace")
    
    def _fix_ports(match):
        host_p = match.group(1)
        cont_p = int(match.group(2))
        # If container port is suspiciously high, it's likely a bug in the bundle creation
        if cont_p > 10000:
            # Try to guess the intended port
            new_cont_p = 80 if "frontend" in compose_text.lower() else 8000
            logger.warning("Repairing suspicious container port %d -> %d", cont_p, new_cont_p)
            cont_p = new_cont_p
        return f'"0:{cont_p}"'

    compose_text = re.sub(r'"(\d+):(\d+)"', _fix_ports, compose_text)

    # 3b. Repair 'networks' block if it contains illegal 'image' or 'env_file' properties
    if "networks:" in compose_text:
        lines = compose_text.splitlines()
        repaired_lines = []
        in_networks = False
        skip_next_if_list = False
        
        for line in lines:
            stripped = line.strip()
            # Detect exit from networks block (any non-indented line that isn't 'networks:')
            if line and not line.startswith(" ") and stripped != "networks:":
                in_networks = False
            
            if stripped == "networks:":
                in_networks = True
            
            if in_networks:
                if stripped.startswith("image:"):
                    continue
                if stripped.startswith("env_file:"):
                    skip_next_if_list = True
                    continue
                if skip_next_if_list and stripped.startswith("-"):
                    continue
                skip_next_if_list = False
                
            repaired_lines.append(line)
        compose_text = "\n".join(repaired_lines)

    # 3c. Repair missing image properties (due to old bundler bug)
    # Scan ALL services and inject image if missing.
    if "services:" in compose_text:
        lines = compose_text.splitlines()
        repaired_lines = []
        in_services = False

        for i, line in enumerate(lines):
            repaired_lines.append(line)
            stripped = line.strip()

            # Track when we enter/exit the services block
            if not line.startswith(" ") and not line.startswith("#") and ":" in stripped:
                in_services = (stripped == "services:")
                continue

            if not in_services:
                continue

            m = re.match(r"^ {2}([a-zA-Z0-9_-]+):", line)
            if not m:
                continue

            service_name = m.group(1)

            # Check if this service block already has an image line
            has_image = False
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Stop at next service or top-level block
                if next_line and not next_line.startswith(" "):
                    break
                if re.match(r"^ {2}[a-zA-Z0-9_-]+:", next_line):
                    break
                if next_line.strip().startswith("image:"):
                    has_image = True
                    break
                j += 1

            if has_image:
                continue

            # No image found — determine the correct one
            block_text = "\n".join(lines[i:j]).lower()
            tag = None

            if service_name in ("frontend", "backend", "app"):
                tag = f"deployer-{compose_project}-{service_name}:latest"
                if service_name == "app":
                    tag = f"deployer-{compose_project}:latest"
            elif "mongo" in block_text or service_name in ("db", "mongodb"):
                tag = "mongo:latest"
            elif "postgres" in block_text or service_name == "postgres":
                tag = "postgres:latest"
            elif "mysql" in block_text or service_name == "mysql":
                tag = "mysql:latest"
            elif "redis" in block_text or service_name == "redis":
                tag = "redis:latest"

            if tag:
                logger.warning("Repairing missing image for service '%s' -> %s", service_name, tag)
                repaired_lines.append(f"    image: {tag}")

        compose_text = "\n".join(repaired_lines)

    # 3d. Relax 'service_healthy' -> 'service_started' in depends_on blocks.
    # When we inject stock database images (mongo, postgres, etc.) the healthcheck may
    # fail or be slow, causing dependent services to abort immediately.
    compose_text = compose_text.replace("condition: service_healthy", "condition: service_started")
    logger.debug("Relaxed all depends_on conditions to service_started")

    compose_file.write_text(compose_text, encoding="utf-8")

    logger.info("Bundle run: docker compose up -d (%s)", compose_project)
    docker_client.compose_up(str(runtime_dir), compose_project, build=False)

    # 4. Query the engine for the ACTUAL ports assigned by Docker.
    # We retry a few times because Docker can take a second to update metadata labels/ports.
    service_ports = []
    for i in range(10):
        service_ports = docker_client.get_compose_port_mappings(compose_project)
        if service_ports:
            break
        import time
        time.sleep(1)
        if i > 2:
            logger.info("Still waiting for ports for %s (attempt %d/10)...", compose_project, i+1)
    
    # Inject full URLs for the proxy
    for sp in service_ports:
        sp["url"] = f"http://localhost:{sp['host_port']}"

    services = list(set(sp["service"] for sp in service_ports))

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
