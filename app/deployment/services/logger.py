"""Per-project structured logger — records LLM calls, builds, pipeline steps, and events as JSONL.

Log channels:
  general   — info/warning/error messages
  llm       — LLM requests and responses
  docker    — image builds and container runs
  analysis  — project analysis results
  pipeline  — deployment pipeline steps
  testing   — test generation and execution
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────

_LEVEL_ICON = {
    "info": "ℹ️ ",
    "warning": "⚠️ ",
    "error": "❌",
    "success": "✅",
    "debug": "🔍",
}

_TYPE_ICON = {
    # LLM
    "request": "📤",
    "response": "📥",
    # Docker
    "build": "🔨",
    "deploy": "🚀",
    # Pipeline
    "step": "🔄",
    "step_start": "▶️ ",
    "step_done": "✅",
    "step_error": "❌",
    # Testing
    "generation": "🧪",
    "execution": "▶️ ",
    # Analysis
    "analysis": "🔍",
}

_CHANNEL_LABEL = {
    "general": "General",
    "llm": "LLM",
    "docker": "Docker",
    "analysis": "Analysis",
    "pipeline": "Pipeline",
    "testing": "Testing",
}


def _fmt_ts(ts: str) -> str:
    """Convert ISO timestamp to readable HH:MM:SS format."""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except Exception:
        return ts[:8] if ts else ""


def format_log_entry(entry: Dict[str, Any], channel: str = "") -> str:
    """Render a single log entry as a human-readable line."""
    ts = _fmt_ts(entry.get("timestamp", ""))
    level = entry.get("level", "")
    etype = entry.get("type", "")
    icon = _TYPE_ICON.get(etype, "") or _LEVEL_ICON.get(level, "📋")

    if channel == "llm" or entry.get("task"):
        task = entry.get("task", "")
        model = entry.get("model", "")
        model_tag = f" model={model}" if model else ""
        if etype == "request":
            tokens = entry.get("prompt_tokens_est")
            tokens_tag = f" ~{tokens} tok" if isinstance(tokens, int) else ""
            return (
                f"{ts}  {icon} LLM {task}{model_tag} → prompt({entry.get('prompt_length', 0)} chars{tokens_tag})"
            )
        elif etype == "response":
            ok = entry.get("success", True)
            status = "OK" if ok else f"FAIL: {entry.get('error', '')}"
            total_tokens = entry.get("total_tokens")
            tokens_tag = f" total={total_tokens}" if isinstance(total_tokens, int) else ""
            return f"{ts}  {icon} LLM {task}{model_tag} ← {status} ({entry.get('response_length', 0)} chars{tokens_tag})"

    if channel == "docker" or etype in ("build", "deploy"):
        if etype == "build":
            tag = entry.get("image_tag", "")
            ok = entry.get("success", True)
            err = entry.get("error", "")
            return f"{ts}  {icon} Build [{tag}] {'✅ OK' if ok else f'❌ FAILED: {err}'}"
        elif etype == "deploy":
            url = entry.get("preview_url", "")
            ok = entry.get("success", True)
            return f"{ts}  {icon} Deploy {'✅' if ok else '❌'} {url}"

    if channel == "pipeline" or etype in ("step", "step_start", "step_done", "step_error"):
        step = entry.get("step", "")
        msg = entry.get("message", "")
        deployment_id = entry.get("deployment_id", "")
        dep_tag = f" [{deployment_id[:8]}]" if deployment_id else ""
        return f"{ts}  {icon} [{step}]{dep_tag} {msg}"

    if channel == "testing":
        if etype == "generation":
            return f"{ts}  {icon} Generated {entry.get('test_count', 0)} test cases"
        elif etype == "execution":
            t, p, f = entry.get("total", 0), entry.get("passed", 0), entry.get("failed", 0)
            return f"{ts}  {icon} Tests: {t} total | ✅ {p} passed | ❌ {f} failed"

    if channel == "analysis":
        pt = entry.get("project_type", "")
        stack = ", ".join(entry.get("tech_stack") or [])
        return f"{ts}  {icon} Analysis complete → {pt} [{stack}]"

    # Fallback
    msg = entry.get("message", json.dumps(entry, ensure_ascii=False)[:120])
    level_tag = f"[{level.upper()}] " if level else ""
    return f"{ts}  {icon} {level_tag}{msg}"


# ─────────────────────────────────────────────────────────────────
# ProjectLogger
# ─────────────────────────────────────────────────────────────────

class ProjectLogger:
    """Structured per-project logging to JSONL files."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._dir = Path(settings.projects_dir) / project_id / ".logs"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _write(self, channel: str, data: Dict[str, Any]) -> None:
        path = self._dir / f"{channel}.jsonl"
        entry = {"timestamp": datetime.now().isoformat(), **data}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    # ── General ──────────────────────────────────────────────────

    def info(self, message: str, **kwargs) -> None:
        self._write("general", {"level": "info", "message": message, **kwargs})
        logger.info("[%s] %s", self.project_id[:8], message)

    def warning(self, message: str, **kwargs) -> None:
        self._write("general", {"level": "warning", "message": message, **kwargs})
        logger.warning("[%s] %s", self.project_id[:8], message)

    def error(self, message: str, error: Optional[Exception] = None, **kwargs) -> None:
        self._write("general", {
            "level": "error",
            "message": message,
            "error": str(error) if error else None,
            **kwargs,
        })
        logger.error("[%s] %s", self.project_id[:8], message)

    def success(self, message: str, **kwargs) -> None:
        self._write("general", {"level": "success", "message": message, **kwargs})
        logger.info("[%s] ✅ %s", self.project_id[:8], message)

    # ── LLM ──────────────────────────────────────────────────────

    def log_llm_request(
        self,
        task: str,
        prompt: str,
        model: str = "",
        prompt_tokens_est: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        self._write("llm", {
            "type": "request",
            "task": task,
            "model": model,
            "prompt_length": len(prompt),
            "prompt_tokens_est": prompt_tokens_est,
            "max_tokens": max_tokens,
            "prompt_preview": prompt[:500],
        })

    def log_llm_response(
        self,
        task: str,
        response: str,
        success: bool = True,
        error: str = "",
        model: str = "",
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
    ) -> None:
        self._write("llm", {
            "type": "response",
            "task": task,
            "success": success,
            "response_length": len(response),
            "response_preview": response[:500],
            "error": error,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        })

    # ── Docker ───────────────────────────────────────────────────

    def log_build(self, image_tag: str, success: bool, error: str = "") -> None:
        self._write("docker", {
            "type": "build",
            "image_tag": image_tag,
            "success": success,
            "error": error,
        })

    def log_deploy(self, container_id: str = "", preview_url: str = "", success: bool = True) -> None:
        self._write("docker", {
            "type": "deploy",
            "container_id": container_id,
            "preview_url": preview_url,
            "success": success,
        })

    # ── Pipeline steps ───────────────────────────────────────────

    def log_pipeline_step(
        self,
        step: str,
        message: str,
        status: str = "running",
        deployment_id: str = "",
        **kwargs,
    ) -> None:
        """Record a deployment pipeline step (analyse/generate/build/run/verify)."""
        icon_map = {"running": "step_start", "done": "step_done", "error": "step_error"}
        self._write("pipeline", {
            "type": icon_map.get(status, "step"),
            "step": step,
            "status": status,
            "message": message,
            "deployment_id": deployment_id,
            **kwargs,
        })
        logger.info("[%s/%s] %s — %s", self.project_id[:8], step, status, message)

    def log_pipeline_error(
        self,
        step: str,
        message: str,
        error: str = "",
        deployment_id: str = "",
    ) -> None:
        self._write("pipeline", {
            "type": "step_error",
            "step": step,
            "status": "error",
            "message": message,
            "error": error,
            "deployment_id": deployment_id,
        })
        logger.error("[%s/%s] ERROR — %s: %s", self.project_id[:8], step, message, error)

    # ── Analysis ─────────────────────────────────────────────────

    def log_analysis(self, project_type: str, tech_stack: list, summary: str = "") -> None:
        self._write("analysis", {
            "type": "analysis",
            "project_type": project_type,
            "tech_stack": tech_stack,
            "summary": summary,
        })

    # ── Testing ──────────────────────────────────────────────────

    def log_test_gen(self, test_count: int, user_prompt: str = "") -> None:
        self._write("testing", {
            "type": "generation",
            "test_count": test_count,
            "user_prompt_preview": user_prompt[:200],
        })

    def log_test_run(self, total: int, passed: int, failed: int) -> None:
        self._write("testing", {
            "type": "execution",
            "total": total,
            "passed": passed,
            "failed": failed,
        })

    # ── Read & format ────────────────────────────────────────────

    def read_logs(self, channel: str = "general", limit: int = 100) -> List[Dict[str, Any]]:
        """Return raw JSONL entries for a channel."""
        path = self._dir / f"{channel}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
        return entries

    def read_logs_formatted(
        self, channel: str = "general", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Return log entries enriched with a human-readable 'text' field."""
        entries = self.read_logs(channel, limit)
        for e in entries:
            e["_channel"] = channel
            e["_text"] = format_log_entry(e, channel)
        return entries

    def get_timeline(
        self,
        limit_per_channel: int = 50,
        channels: Optional[List[str]] = None,
        deployment_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return a unified chronological timeline across all (or selected) channels.

        Each entry gains: ``_channel``, ``_text`` (human-readable line).
        Optionally filter by deployment_id for deployment-scoped views.
        """
        all_channels = channels or self.get_all_channels()
        merged = []
        for ch in all_channels:
            for e in self.read_logs(ch, limit_per_channel):
                if deployment_id and e.get("deployment_id") and e["deployment_id"] != deployment_id:
                    continue
                e["_channel"] = ch
                e["_channel_label"] = _CHANNEL_LABEL.get(ch, ch.capitalize())
                e["_text"] = format_log_entry(e, ch)
                merged.append(e)
        merged.sort(key=lambda x: x.get("timestamp", ""))
        return merged

    def get_all_channels(self) -> List[str]:
        """Return list of existing log channel names."""
        if not self._dir.exists():
            return []
        return [p.stem for p in sorted(self._dir.glob("*.jsonl"))]

    def get_channel_stats(self, channel: str) -> Dict[str, Any]:
        """Return entry count, first/last timestamps for a channel."""
        entries = self.read_logs(channel, limit=10000)
        if not entries:
            return {"channel": channel, "count": 0}
        return {
            "channel": channel,
            "label": _CHANNEL_LABEL.get(channel, channel),
            "count": len(entries),
            "first": entries[0].get("timestamp"),
            "last": entries[-1].get("timestamp"),
            "error_count": sum(
                1 for e in entries
                if e.get("level") == "error" or e.get("type") in ("step_error",)
            ),
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return per-channel statistics and metadata for a project."""
        channels = self.get_all_channels()
        channel_stats = [self.get_channel_stats(ch) for ch in channels]
        total_entries = sum(s["count"] for s in channel_stats)
        total_errors = sum(s.get("error_count", 0) for s in channel_stats)

        return {
            "project_id": self.project_id,
            "total_log_entries": total_entries,
            "total_errors": total_errors,
            "channels": channel_stats,
            "available_channels": channels,
            "log_dir": str(self._dir),
        }


# ─────────────────────────────────────────────────────────────────
# LoggerManager
# ─────────────────────────────────────────────────────────────────

class LoggerManager:
    """Singleton factory for per-project loggers."""

    _loggers: Dict[str, ProjectLogger] = {}

    @classmethod
    def get(cls, project_id: str) -> ProjectLogger:
        if project_id not in cls._loggers:
            cls._loggers[project_id] = ProjectLogger(project_id)
        return cls._loggers[project_id]
