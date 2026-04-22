"""Thin wrapper around the Docker SDK — isolates all Docker engine interactions."""

from __future__ import annotations

import logging
import socket
from typing import Any, Dict, List, Optional

from app.deployment.core.exceptions import DockerError

logger = logging.getLogger(__name__)

try:
    import docker
    from docker.errors import DockerException, BuildError, APIError
except ImportError:
    docker = None  # type: ignore[assignment]


class DockerClient:
    """Manages interactions with the Docker daemon."""

    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if docker is None:
                raise DockerError("docker Python package is not installed")
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:
                raise DockerError(f"Cannot connect to Docker daemon: {exc}") from exc
        return self._client

    def is_available(self) -> bool:
        try:
            _ = self.client
            return True
        except DockerError:
            return False

    # ── Build ────────────────────────────────────────────────────

    def build_image(
        self,
        path: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        *,
        log_collector: list | None = None,
    ) -> str:
        """Build a Docker image and return its ID.

        If *log_collector* is passed, each build-log line is appended to it.
        """
        logger.info("Building image %s from %s", tag, path)
        try:
            image, build_logs = self.client.images.build(
                path=path,
                tag=tag,
                dockerfile=dockerfile,
                rm=True,
                forcerm=True,
            )
            # Collect logs
            for chunk in build_logs:
                if "stream" in chunk:
                    line = chunk["stream"].strip()
                    if line:
                        logger.debug("  %s", line)
                        if log_collector is not None:
                            log_collector.append(line)
            logger.info("Image built: %s (%s)", tag, image.id[:12])
            return image.id
        except BuildError as exc:
            logs = "\n".join(
                chunk.get("stream", chunk.get("error", ""))
                for chunk in exc.build_log
                if chunk.get("stream") or chunk.get("error")
            )
            if log_collector is not None:
                log_collector.append(f"BUILD ERROR:\n{logs}")
            raise DockerError(f"Docker build failed: {exc}\n{logs}") from exc
        except Exception as exc:
            raise DockerError(f"Docker build error: {exc}") from exc

    # ── Run ──────────────────────────────────────────────────────

    def run_container(
        self,
        image: str,
        *,
        name: str | None = None,
        ports: Dict[str, int] | None = None,
        fixed_ports: Dict[int, int] | None = None,
        environment: Dict[str, str] | None = None,
        detach: bool = True,
    ) -> Dict[str, Any]:
        """Run a container and return summary info (id, ports, name)."""
        port_bindings = {}
        if fixed_ports:
            for container_port, host_port in fixed_ports.items():
                port_bindings[f"{container_port}/tcp"] = host_port
        elif ports:
            for _service, container_port in ports.items():
                host_port = self._find_free_port()
                port_bindings[f"{container_port}/tcp"] = host_port

        try:
            container = self.client.containers.run(
                image,
                name=name,
                ports=port_bindings,
                environment=environment or {},
                detach=detach,
                remove=False,
            )
            container.reload()

            # Collect actual host port mappings
            mapped_ports: List[Dict[str, Any]] = []
            for c_port, bindings in (container.attrs["NetworkSettings"]["Ports"] or {}).items():
                if bindings:
                    mapped_ports.append({
                        "containerPort": int(c_port.split("/")[0]),
                        "hostPort": int(bindings[0]["HostPort"]),
                        "service": "app",
                    })

            return {
                "container_id": container.id,
                "name": container.name,
                "ports": mapped_ports,
                "status": container.status,
            }
        except Exception as exc:
            raise DockerError(f"Failed to run container: {exc}") from exc

    # ── Container management ─────────────────────────────────────

    def get_status(self, container_id: str) -> str:
        try:
            container = self.client.containers.get(container_id)
            container.reload()
            return container.status  # running, exited, etc.
        except Exception:
            return "unknown"

    def stop_container(self, container_id: str) -> None:
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            logger.info("Stopped container %s", container_id[:12])
        except Exception as exc:
            logger.warning("Failed to stop container %s: %s", container_id[:12], exc)

    def start_container(self, container_id: str) -> None:
        try:
            container = self.client.containers.get(container_id)
            container.start()
            logger.info("Started container %s", container_id[:12])
        except Exception as exc:
            raise DockerError(f"Failed to start container: {exc}") from exc

    def get_logs(self, container_id: str, tail: int = 200) -> str:
        try:
            container = self.client.containers.get(container_id)
            return container.logs(tail=tail).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def remove_container(self, container_id: str) -> None:
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True)
        except Exception:
            pass

    def remove_images(self, image_refs: List[str]) -> None:
        for image_ref in image_refs:
            try:
                self.client.images.remove(image=image_ref, force=False, noprune=False)
                logger.info("Removed image %s", image_ref)
            except Exception as exc:
                logger.warning("Failed to remove image %s: %s", image_ref, exc)

    # ── Compose ──────────────────────────────────────────────────

    def compose_up(
        self,
        project_dir: str,
        project_name: str | None = None,
        *,
        build: bool = True,
    ) -> str:
        """Run docker compose up -d in the given directory."""
        import subprocess

        cmd = ["docker", "compose"]
        if project_name:
            cmd += ["-p", project_name]
        cmd += ["up", "-d"]
        if build:
            cmd += ["--build"]

        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise DockerError(f"docker compose up failed:\n{result.stderr}")
        return result.stdout

    def compose_down(
        self,
        project_dir: str,
        project_name: str | None = None,
        *,
        remove_volumes: bool = False,
    ) -> None:
        import subprocess

        cmd = ["docker", "compose"]
        if project_name:
            cmd += ["-p", project_name]
        cmd += ["down", "--remove-orphans"]
        if remove_volumes:
            cmd += ["--volumes"]

        subprocess.run(cmd, cwd=project_dir, capture_output=True, timeout=60)

    def compose_stop(
        self,
        project_dir: str,
        project_name: str | None = None,
    ) -> None:
        import subprocess

        cmd = ["docker", "compose"]
        if project_name:
            cmd += ["-p", project_name]
        cmd += ["stop"]

        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise DockerError(f"docker compose stop failed:\n{result.stderr}")

    def get_compose_logs(
        self, project_dir: str, project_name: str | None = None, tail: int = 200,
    ) -> str:
        """Get logs from all services in a compose project."""
        import subprocess

        cmd = ["docker", "compose"]
        if project_name:
            cmd += ["-p", project_name]
        cmd += ["logs", "--tail", str(tail), "--no-color"]

        result = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True, timeout=30,
        )
        return result.stdout or result.stderr

    # ── Image save / load (.tar.gz) ────────────────────────────────

    def save_image(self, image_tag: str, output_path: str) -> None:
        """Save a Docker image as a compressed .tar.gz archive."""
        import gzip

        try:
            image = self.client.images.get(image_tag)
            raw_tar = image.save(named=True)

            with gzip.open(output_path, "wb", compresslevel=6) as gz:
                for chunk in raw_tar:
                    gz.write(chunk)

            logger.info("Image saved: %s → %s", image_tag, output_path)
        except Exception as exc:
            raise DockerError(f"Failed to save image {image_tag}: {exc}") from exc

    def load_image(self, tar_path: str) -> str:
        """Load a Docker image from a .tar.gz archive. Returns the image tag."""
        import gzip

        try:
            # Decompress and load
            with gzip.open(tar_path, "rb") as gz:
                result = self.client.images.load(gz.read())

            if result:
                loaded = result[0]
                tag = loaded.tags[0] if loaded.tags else loaded.id
                logger.info("Image loaded: %s → %s", tar_path, tag)
                return tag
            raise DockerError("No image returned after load")
        except Exception as exc:
            raise DockerError(f"Failed to load image from {tar_path}: {exc}") from exc

    def load_images_tar(self, tar_path: str) -> str:
        """Load one or more Docker images from an uncompressed tar archive."""
        import subprocess

        cmd = ["docker", "load", "-i", tar_path]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise DockerError(f"docker load failed:\n{result.stderr or result.stdout}")
        return result.stdout

    def list_saved_images(self, project_dir: str) -> list:
        """List all saved .tar.gz images in a project's images directory."""
        from pathlib import Path
        images_dir = Path(project_dir) / "images"
        if not images_dir.exists():
            return []

        def _service_name(p: Path) -> str:
            name = p.name
            if name.endswith(".tar.gz"):
                name = name[: -len(".tar.gz")]
            if name.endswith(".tar"):
                name = name[: -len(".tar")]
            return name

        return [
            {
                "service": _service_name(p),
                "path": str(p),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 1),
            }
            for p in images_dir.glob("*.tar.gz")
        ]

    def tag_image(self, source: str, target: str) -> None:
        """Retag an existing local image (source) to a new repo:tag (target)."""
        try:
            image = self.client.images.get(source)
            if ":" in target:
                repo, tag = target.rsplit(":", 1)
            else:
                repo, tag = target, "latest"
            image.tag(repository=repo, tag=tag)
        except Exception as exc:
            raise DockerError(f"Failed to tag image {source} -> {target}: {exc}") from exc

    # ── Helpers ──────────────────────────────────────────────────

    def _find_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]


# Singleton
docker_client = DockerClient()
