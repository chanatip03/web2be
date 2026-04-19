"""Deployment acceptance checks — HTTP probing before marking success.

After a container starts, probe its HTTP endpoints to verify it's actually
serving traffic, not just "running" but crashing immediately.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx
from app.deployment.core.config import settings

logger = logging.getLogger(__name__)

# Common health/probe paths ordered by likelihood
_DEFAULT_PROBE_PATHS = [
    "/",
    "/health",
    "/healthz",
    "/api",
    "/api/health",
    "/status",
    "/ping",
]


def _probe_paths_for_service(service: str) -> List[str]:
    configured = [p.strip() for p in (getattr(settings, "readiness_probe_paths", "") or "").split(",") if p.strip()]
    base = configured or list(_DEFAULT_PROBE_PATHS)
    if service == "backend":
        preferred = ["/health", "/healthz", "/api/health", "/status", "/ping", "/api", "/"]
    elif service == "frontend":
        preferred = ["/", "/index.html", "/health", "/status"]
    else:
        preferred = list(base)

    out: List[str] = []
    seen = set()
    for path in preferred + base:
        if path not in seen:
            out.append(path)
            seen.add(path)
    return out


async def run_acceptance_checks(
    *,
    service_ports: List[Dict[str, Any]],
    timeout_seconds: float = 30.0,
    poll_interval: float = 2.0,
    acceptable_codes: set[int] | None = None,
) -> Dict[str, Any]:
    """Probe all services until they respond or timeout.

    Args:
        service_ports: List of {"service": "...", "host_port": ..., "url": "..."}.
        timeout_seconds: Max time to wait for all services.
        poll_interval: Seconds between retry polls.
        acceptable_codes: HTTP status codes considered "healthy" (default 2xx + 3xx + 404).

    Returns:
        {"passed": bool, "services": {service: {status, code, latency_ms, url}}}
    """
    if acceptable_codes is None:
        acceptable_codes = set(range(200, 400)) | {401, 403, 404, 405}

    results: Dict[str, Dict[str, Any]] = {}
    pending = {sp["service"]: sp for sp in service_ports if sp["service"] != "db"}

    if not pending:
        return {"passed": True, "services": {}, "message": "No services to probe"}

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    attempt = 0

    while pending and asyncio.get_event_loop().time() < deadline:
        attempt += 1
        logger.info("Acceptance probe attempt %d for %s", attempt, list(pending.keys()))

        tasks = {
            svc: _probe_service(
                # In Docker-in-Docker mode, the scanner container cannot reach
                # localhost:<host_port> because localhost resolves to the scanner
                # container itself. Use host.docker.internal to reach the host.
                sp["url"].replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal"),
                acceptable_codes,
                _probe_paths_for_service(svc),
            )
            for svc, sp in pending.items()
        }

        probe_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        for svc, result in zip(tasks.keys(), probe_results):
            if isinstance(result, Exception):
                logger.error(f"Probe error for {svc}: {result}")
                results[svc] = {"status": "error", "error": str(result)}
                continue

            if result.get("healthy"):
                results[svc] = {
                    "status": "healthy",
                    "code": result["code"],
                    "latency_ms": result["latency_ms"],
                    "url": result["url"],
                    "path": result["path"],
                }
                # Remove from pending
                del pending[svc]  # Will break iteration but we break below

                # need to rebuild pending after mutation
            elif result.get("tcp_listening"):
                results[svc] = {
                    "status": "degraded",
                    "code": result.get("code"),
                    "latency_ms": result.get("latency_ms"),
                    "url": result.get("url"),
                    "path": result.get("path"),
                    "error": "TCP listening but HTTP readiness not healthy yet",
                }
        # Remove healthy services from pending
        for svc in list(pending.keys()):
            if svc in results and results[svc].get("status") == "healthy":
                del pending[svc]

        if pending:
            await asyncio.sleep(poll_interval)

    # Mark remaining as failed
    for svc, sp in pending.items():
        if svc not in results:
            results[svc] = {"status": "timeout", "error": f"No response within {timeout_seconds}s"}

    all_passed = all(r.get("status") == "healthy" for r in results.values())
    return {
        "passed": all_passed,
        "services": results,
        "attempts": attempt,
        "message": "All services healthy" if all_passed else "Some services failed health check",
    }


async def _probe_service(
    base_url: str,
    acceptable_codes: set[int],
    probe_paths: List[str],
) -> Dict[str, Any]:
    """Try multiple paths on a service until one responds."""
    base = base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        for path in probe_paths:
            url = f"{base}{path}"
            try:
                import time
                t0 = time.perf_counter()
                resp = await client.get(url)
                latency = (time.perf_counter() - t0) * 1000

                if resp.status_code in acceptable_codes:
                    return {
                        "healthy": True,
                        "code": resp.status_code,
                        "latency_ms": round(latency, 1),
                        "url": url,
                        "path": path,
                    }
                else:
                    logger.debug(f"Probe {url} returned {resp.status_code} (unhealthy)")
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.debug(f"Probe {url} failed: {type(exc).__name__}")
                continue
            except Exception as exc:
                logger.debug(f"Probe {url} unexpected error: {exc}")
                continue

    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    tcp_ok = await _probe_tcp(host, int(port), timeout=2.5)
    return {
        "healthy": False,
        "tcp_listening": tcp_ok,
        "code": None,
        "latency_ms": None,
        "url": base,
        "path": None,
    }


async def _probe_tcp(host: str, port: int, timeout: float) -> bool:
    try:
        conn = asyncio.open_connection(host, port)
        _reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
