"""Runtime bundler — create a self-contained portable .tar.gz artifact.

The bundle contains everything needed to deploy on ANY Docker host:
  {project_id}.tar.gz
    ├── images.tar            (all Docker images: frontend, backend, DB)
    ├── docker-compose.yml    (ready to run)
    └── .env                  (environment variables)

Usage on target machine:
  tar xzf project.tar.gz
  docker load -i images.tar
  docker compose up -d
"""

from __future__ import annotations

import gzip
import io
import logging
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings
from app.deployment.models.deployment import DeploymentStatus
from app.deployment.models.project import ProjectAnalysis

logger = logging.getLogger(__name__)


async def create_bundle(
    *,
    project_id: str,
    deployment: DeploymentStatus,
    project_path: Path,
    analysis: Optional[ProjectAnalysis] = None,
    include_db_image: bool = True,
) -> Path:
    """Create a self-contained portable .tar.gz bundle.

    Returns the path to the bundle file.
    """
    from app.deployment.services.docker.client import docker_client

    bundle_dir = Path(settings.deployments_dir) / "bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{project_id}.tar.gz"

    # Collect all image tags to bundle
    image_tags: List[str] = []

    # Service images
    if deployment.image_tags and isinstance(deployment.image_tags, dict):
        image_tags.extend(deployment.image_tags.values())
    elif deployment.image_tag:
        image_tags.append(deployment.image_tag)

    # DB image (pull if needed)
    if include_db_image and analysis:
        db_info = analysis.database_info or {}
        if db_info.get("detected"):
            db_type = (db_info.get("type") or "").lower()
            db_images = {
                "postgresql": "postgres:16-alpine",
                "postgres": "postgres:16-alpine",
                "mysql": "mysql:8.0",
                "mariadb": "mariadb:11",
                "mongodb": "mongo:7",
                "mongo": "mongo:7",
                "redis": "redis:7-alpine",
            }
            db_image = db_images.get(db_type)
            if db_image and db_image not in image_tags:
                try:
                    # Prefer strictly self-contained bundles: only include images
                    # that are already local. Pulling can be enabled via settings.
                    try:
                        docker_client.client.images.get(db_image)
                        image_tags.append(db_image)
                        logger.info("Including local DB image for bundle: %s", db_image)
                    except Exception:
                        if settings.bundle_allow_pull_db_image:
                            docker_client.client.images.pull(db_image)
                            image_tags.append(db_image)
                            logger.info("Pulled DB image for bundle: %s", db_image)
                        else:
                            raise ValueError(
                                f"DB image {db_image} is not available locally. "
                                "Pull it first or set BUNDLE_ALLOW_PULL_DB_IMAGE=true."
                            )
                except ValueError:
                    raise
                except Exception as exc:
                    logger.warning("Could not pull DB image %s: %s", db_image, exc)

    if not image_tags:
        raise ValueError("No images available to bundle")

    # Create bundle in temp directory
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # 1. Save all images into a single images.tar
        images_tar_path = tmp_path / "images.tar"
        logger.info("Saving %d image(s) to images.tar: %s", len(image_tags), image_tags)
        _save_images_to_tar(image_tags, images_tar_path)

        # 2. Get or generate docker-compose.yml
        compose_path = tmp_path / "docker-compose.yml"
        compose_raw = _get_compose_content(deployment, project_path, analysis)
        compose_content = _make_compose_portable(compose_raw)
        compose_path.write_text(compose_content, encoding="utf-8")

        # 2b. Copy any required runtime assets referenced by compose (e.g. seed.sql)
        extra_paths = _stage_compose_runtime_assets(
            compose_content=compose_content,
            source_root=project_path,
            bundle_root=tmp_path,
        )

        # 3. Get or generate .env
        env_path = tmp_path / ".env"
        env_content = await _get_env_content(project_path, analysis)
        env_path.write_text(env_content, encoding="utf-8")

        # 4. Create README
        readme_path = tmp_path / "README.md"
        readme_path.write_text(_generate_readme(project_id, image_tags, deployment), encoding="utf-8")

        # 5. Pack everything into .tar.gz
        logger.info("Creating bundle: %s", bundle_path)
        with tarfile.open(str(bundle_path), "w:gz", compresslevel=6) as tar:
            tar.add(str(images_tar_path), arcname="images.tar")
            tar.add(str(compose_path), arcname="docker-compose.yml")
            tar.add(str(env_path), arcname=".env")
            tar.add(str(readme_path), arcname="README.md")
            for p in extra_paths:
                if p.exists() and p.is_file():
                    tar.add(str(p), arcname=str(p.relative_to(tmp_path)))

    bundle_size_mb = round(bundle_path.stat().st_size / (1024 * 1024), 1)
    logger.info("Bundle created: %s (%.1f MB)", bundle_path, bundle_size_mb)

    return bundle_path


def _save_images_to_tar(image_tags: List[str], output_path: Path) -> None:
    """Save multiple Docker images into a single tar file."""
    import docker
    client = docker.from_env()

    images = []
    for tag in image_tags:
        try:
            images.append(client.images.get(tag))
        except docker.errors.ImageNotFound:
            logger.warning("Image not found, skipping: %s", tag)

    if not images:
        raise ValueError("No images found to save")

    # Docker SDK: save multiple images at once
    chunks = client.images.get(image_tags[0]).save(named=True)
    if len(image_tags) > 1:
        # For multiple images, save them individually and combine into one tar
        with open(str(output_path), "wb") as f:
            for tag in image_tags:
                try:
                    img = client.images.get(tag)
                    for chunk in img.save(named=True):
                        f.write(chunk)
                except Exception as exc:
                    logger.warning("Failed to save image %s: %s", tag, exc)
    else:
        with open(str(output_path), "wb") as f:
            for chunk in chunks:
                f.write(chunk)


def _get_compose_content(
    deployment: DeploymentStatus, 
    project_path: Path,
    analysis: Optional[ProjectAnalysis] = None
) -> str:
    """Get the docker-compose.yml content — from deployment or file."""
    # Try existing compose file
    if deployment.compose_file_path:
        p = Path(deployment.compose_file_path)
        if p.exists():
            return p.read_text(encoding="utf-8")

    # Try finding in project
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        p = project_path / name
        if p.exists():
            return p.read_text(encoding="utf-8")

    # Generate a simple one
    image = deployment.image_tag or "app:latest"
    host_port = deployment.host_port or 8000
    container_port = 8000 # Default

    # Logic to find the correct container port
    found_port = False
    if deployment.service_ports:
        # Prefer the 'primary' service port (frontend or app)
        for pref in ("frontend", "app", "backend"):
            for sp in deployment.service_ports:
                if sp.service == pref:
                    # Handle both dict and Pydantic model (depending on code path)
                    if hasattr(sp, "container_port"):
                        container_port = sp.container_port
                    else:
                        container_port = sp.get("container_port", 8000)
                    found_port = True
                    break
            if found_port: break
        
        # Fallback to the first available service port if no priority match
        if not found_port and deployment.service_ports:
            sp = deployment.service_ports[0]
            if hasattr(sp, "container_port"):
                container_port = sp.container_port
            else:
                container_port = sp.get("container_port", 8000)
            found_port = True

    if not found_port:
        # Heuristic fallback based on project type
        mode = (deployment.deploy_mode or "").lower()
        if mode == "static-html" or "frontend" in image.lower():
            container_port = 80
        elif host_port > 1024:
            # If no better info, assume container port matches host port (e.g. 8000:8000)
            container_port = host_port

    db_service = ""
    db_env = ""
    
    if analysis and analysis.database_info and analysis.database_info.get("detected"):
        db_type = (analysis.database_info.get("type") or "").lower()
        db_images = {
            "postgresql": "postgres:16-alpine",
            "postgres": "postgres:16-alpine",
            "mysql": "mysql:8.0",
            "mariadb": "mariadb:11",
            "mongodb": "mongo:7",
            "mongo": "mongo:7",
            "redis": "redis:7-alpine",
        }
        db_image = db_images.get(db_type)
        if db_image:
            db_service = f"""
  db:
    image: {db_image}
    environment:
      POSTGRES_DB: app_db
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app_secret
      MYSQL_DATABASE: app_db
      MYSQL_USER: app
      MYSQL_PASSWORD: app_secret
      MYSQL_ROOT_PASSWORD: root_secret
      MONGO_INITDB_ROOT_USERNAME: app
      MONGO_INITDB_ROOT_PASSWORD: app_secret
    restart: unless-stopped"""
            # Inject connection info for the app
            db_port = "5432" if "postgres" in db_type else "3306"
            if "mongo" in db_type:
                db_port = "27017"
            elif "redis" in db_type:
                db_port = "6379"
            
            db_env = f"""
    environment:
      - DATABASE_URL={db_type}://app:app_secret@db:{db_port}/app_db
      - DB_HOST=db
      - DB_PORT={db_port}
      - DB_USER=app
      - DB_PASSWORD=app_secret
      - DB_NAME=app_db"""

    return f"""# Auto-generated for portable deployment
services:
  app:
    image: {image}
    ports:
      - "{host_port}:{container_port}"
    env_file:
      - .env{db_env}
    restart: unless-stopped{db_service}
"""


def _make_compose_portable(content: str) -> str:
    """Make compose file portable by adding env_file reference."""
    import re

    # Add env_file if not already present
    if "env_file" not in content:
        # Add env_file under each service that has 'image:'
        lines = content.split("\n")
        new_lines = []
        in_service = False
        for line in lines:
            new_lines.append(line)
            # Detect service-level image: or build: line
            stripped = line.strip()
            if stripped.startswith("image:") and in_service:
                indent = len(line) - len(line.lstrip())
                new_lines.append(" " * indent + "env_file:")
                new_lines.append(" " * indent + "  - .env")
            if stripped.endswith(":") and not stripped.startswith("#") and not stripped.startswith("-"):
                in_service = True
        content = "\n".join(new_lines)

    # Replace dynamic host ports with container ports for portability
    # e.g., "54321:8000" → "8000:8000"
    content = re.sub(
        r'"(\d+):(\d+)"',
        lambda m: f'"{m.group(2)}:{m.group(2)}"',
        content,
    )

    return content


def _stage_compose_runtime_assets(
    *,
    compose_content: str,
    source_root: Path,
    bundle_root: Path,
) -> List[Path]:
    """Copy runtime assets referenced by compose into the bundle temp dir.

    Primary use-case: DB seed/init SQL bind-mounted into the DB container.
    Returns a list of *bundle_root* paths that should be included in the tar.
    """
    import re

    staged: List[Path] = []

    # Capture host-path part of a bind mount that targets seed.sql.
    # Examples:
    #   - ./.deploy/seed.sql:/docker-entrypoint-initdb.d/seed.sql:ro
    #   - "./backend/seed.sql:/docker-entrypoint-initdb.d/seed.sql:ro"
    mount_re = re.compile(
        r"^\s*-\s*(?P<src>[^:]+):/docker-entrypoint-initdb\.d/seed\.sql(?:\:ro|\:rw)?\s*$"
    )

    for raw_line in compose_content.splitlines():
        line = raw_line.strip().strip('"').strip("'")
        m = mount_re.match(line)
        if not m:
            continue

        src = m.group("src").strip().strip('"').strip("'")
        if not src.startswith("./"):
            # We only support staging project-relative paths into the bundle.
            logger.warning("Bundle: unsupported seed mount (not project-relative): %s", src)
            continue

        rel = Path(src[2:])
        src_path = (source_root / rel).resolve()
        if not src_path.exists() or not src_path.is_file():
            logger.warning("Bundle: referenced seed file not found: %s", src_path)
            continue

        dest_path = bundle_root / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        staged.append(dest_path)

    # Also include a common deploy directory if present (safe default)
    deploy_dir = source_root / ".deploy"
    if deploy_dir.exists() and deploy_dir.is_dir():
        for p in deploy_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(source_root)
                dest_path = bundle_root / rel
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest_path)
                staged.append(dest_path)

    # Dedup
    uniq: List[Path] = []
    seen = set()
    for p in staged:
        key = str(p)
        if key not in seen:
            uniq.append(p)
            seen.add(key)
    return uniq


async def _get_env_content(
    project_path: Path,
    analysis: Optional[ProjectAnalysis],
) -> str:
    """Get .env content — from project or generate one via LLM (LLM-only mode)."""
    from app.deployment.services.analyzer.file_scanner import build_file_tree, sample_key_files
    from app.deployment.services.docker.env_generator import find_existing_env, generate_env_with_llm

    existing = find_existing_env(project_path)
    if existing:
        return existing

    if analysis is None:
        raise ValueError("Cannot generate .env for bundle: missing project analysis")

    file_tree = str(build_file_tree(project_path))
    file_samples = str(sample_key_files(project_path))
    return await generate_env_with_llm(project_path, analysis, file_tree, file_samples)


def _generate_readme(
    project_id: str,
    image_tags: List[str],
    deployment: DeploymentStatus,
) -> str:
    """Generate a README for the bundle."""
    services = ", ".join(deployment.compose_services or ["app"])
    return f"""# Deployment Bundle: {project_id[:8]}

## Quick Start

1. Load Docker images:
   ```bash
   docker load -i images.tar
   ```

2. Start services:
   ```bash
   docker compose up -d
   ```

3. Access the app at the ports defined in docker-compose.yml

## Contents

- `images.tar` — Docker images: {', '.join(image_tags)}
- `docker-compose.yml` — Service definitions ({services})
- `.env` — Environment variables (edit for production!)

## Services

Deploy mode: {deployment.deploy_mode}

## Notes

- Edit `.env` before deploying to production
- The `.env` file contains development/mock values by default
- All images are pre-built and ready to run
"""


def list_bundles() -> List[Dict[str, Any]]:
    """List all available bundles."""
    bundle_dir = Path(settings.deployments_dir) / "bundles"
    if not bundle_dir.exists():
        return []

    return [
        {
            "project_id": p.stem,
            "path": str(p),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 1),
            "created_at": p.stat().st_mtime,
        }
        for p in bundle_dir.glob("*.tar.gz")
    ]
