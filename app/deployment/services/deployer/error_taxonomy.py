from __future__ import annotations

import re
from typing import Any, Dict


def classify_deploy_error(error_message: str, build_logs: str = "", runtime_logs: str = "") -> Dict[str, Any]:
    text = "\n".join([error_message or "", build_logs or "", runtime_logs or ""]).lower()

    rules = [
        {
            "code": "db_seed_invalid",
            "pattern": r"table '.*' doesn't exist|running /docker-entrypoint-initdb.d/seed\.sql|seed\.sql",
            "retryable": False,
            "action": "Sanitize seed SQL or generate fallback schema before compose up.",
        },
        {
            "code": "db_auth_mismatch",
            "pattern": r"access denied for user|could not connect to db after multiple retries|db_pass|db_password",
            "retryable": False,
            "action": "Normalize DB env aliases and keep compose DB credentials aligned.",
        },
        {
            "code": "db_not_ready",
            "pattern": r"connection failed, retrying|dependency failed to start: container .* is unhealthy|service_healthy",
            "retryable": True,
            "action": "Increase readiness retries/start period and keep backend depends_on=service_healthy.",
        },
        {
            "code": "frontend_build_tooling_missing",
            "pattern": r"sh: vite: not found|module not found|npm err!",
            "retryable": False,
            "action": "Use install strategy that includes required build dependencies for the detected framework.",
        },
        {
            "code": "proxy_upstream_disconnect",
            "pattern": r"proxy error|server disconnected without sending a response|502",
            "retryable": True,
            "action": "Treat as readiness/routing issue and re-check service health + port mapping.",
        },
        {
            "code": "llm_timeout_or_rate_limit",
            "pattern": r"429|timeout|retry-after|lightning ai returned",
            "retryable": True,
            "action": "Apply bounded retry with backoff and avoid making LLM decisions in critical paths.",
        },
        {
            "code": "docker_build_failed",
            "pattern": r"build failed|returned a non-zero code|failed to solve",
            "retryable": False,
            "action": "Apply deterministic Dockerfile hardening/repair policy, then retry build.",
        },
    ]

    for rule in rules:
        if re.search(rule["pattern"], text, flags=re.IGNORECASE):
            return {
                "code": rule["code"],
                "retryable": rule["retryable"],
                "suggested_action": rule["action"],
            }

    return {
        "code": "unknown_deploy_failure",
        "retryable": False,
        "suggested_action": "Inspect build/runtime logs and add a deterministic remediation rule.",
    }
