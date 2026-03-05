"""Health checker — monitors container health via Docker stats and HTTP probes."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.deployment.services.docker.client import docker_client

logger = logging.getLogger(__name__)


class HealthChecker:
    """Check health of deployed containers."""

    async def check_container(self, container_id: str) -> Dict[str, Any]:
        """Full health check for a single container."""
        result: Dict[str, Any] = {
            "container_id": container_id,
            "docker_status": "unknown",
            "healthy": False,
            "resource_usage": None,
            "http_check": None,
        }

        # Docker status
        try:
            status = docker_client.get_status(container_id)
            result["docker_status"] = status
            result["healthy"] = status == "running"
        except Exception as exc:
            result["docker_status"] = f"error: {exc}"
            return result

        # Resource usage
        try:
            container = docker_client.client.containers.get(container_id)
            stats = container.stats(stream=False)
            cpu = self._calc_cpu_percent(stats)
            mem = stats.get("memory_stats", {})
            result["resource_usage"] = {
                "cpu_percent": round(cpu, 2),
                "memory_usage_mb": round(mem.get("usage", 0) / (1024 * 1024), 1),
                "memory_limit_mb": round(mem.get("limit", 0) / (1024 * 1024), 1),
            }
        except Exception:
            pass

        return result

    async def check_http(self, url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Probe an HTTP endpoint."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                return {
                    "url": url,
                    "status_code": resp.status_code,
                    "healthy": 200 <= resp.status_code < 500,
                    "response_time_ms": resp.elapsed.total_seconds() * 1000 if resp.elapsed else None,
                }
        except Exception as exc:
            return {
                "url": url,
                "healthy": False,
                "error": str(exc),
            }

    async def check_all_containers(self) -> List[Dict[str, Any]]:
        """Check health of all running deployer containers."""
        results = []
        try:
            # Legacy naming used: dep-xxxxxxxx
            # New naming uses project UUIDs directly; compose containers start with "{uuid}-...".
            uuid_prefix = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
            containers = docker_client.client.containers.list()
            containers = [
                c for c in containers
                if (c.name.startswith("dep-") or uuid_prefix.match(c.name or ""))
            ]
            for c in containers:
                result = await self.check_container(c.id)
                result["name"] = c.name
                results.append(result)
        except Exception as exc:
            logger.warning("Failed to list containers: %s", exc)
        return results

    def _calc_cpu_percent(self, stats: Dict[str, Any]) -> float:
        try:
            cpu = stats["cpu_stats"]
            pre = stats["precpu_stats"]
            delta = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
            system_delta = cpu["system_cpu_usage"] - pre["system_cpu_usage"]
            n_cpus = len(cpu["cpu_usage"].get("percpu_usage", [1]))
            if system_delta > 0:
                return (delta / system_delta) * n_cpus * 100.0
        except (KeyError, ZeroDivisionError):
            pass
        return 0.0


health_checker = HealthChecker()
