"""LLM Conversation Logger — records every prompt/response for debugging.

Stores conversations as JSONL files per project, queryable via API.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings

logger = logging.getLogger(__name__)


class ConversationEntry:
    """A single LLM interaction."""

    def __init__(
        self,
        *,
        project_id: str,
        step: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        request_payload: Optional[Dict[str, Any]] = None,
        response_json: Optional[Dict[str, Any]] = None,
        model: str,
        temperature: float,
        duration_ms: float,
        success: bool = True,
        error: Optional[str] = None,
        prompt_tokens_est: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ):
        self.timestamp = datetime.now().isoformat()
        self.project_id = project_id
        self.step = step
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.response = response
        self.request_payload = request_payload
        self.response_json = response_json
        self.model = model
        self.temperature = temperature
        self.duration_ms = duration_ms
        self.success = success
        self.error = error
        self.prompt_tokens_est = prompt_tokens_est
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.max_tokens = max_tokens

    def to_dict(self, *, truncate: bool = True) -> Dict[str, Any]:
        system_prompt = self.system_prompt
        user_prompt = self.user_prompt
        response = self.response
        request_payload = self.request_payload
        response_json = self.response_json

        if truncate:
            system_prompt = (system_prompt or "")[:2000]
            user_prompt = (user_prompt or "")[:5000]
            response = (response or "")[:10000]

        return {
            "timestamp": self.timestamp,
            "project_id": self.project_id,
            "step": self.step,
            "model": self.model,
            "temperature": self.temperature,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "prompt_tokens_est": self.prompt_tokens_est,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "request_payload": request_payload,
            "response_json": response_json,
        }


class LLMConversationLogger:
    """Persist LLM conversations to JSONL files per project."""

    def __init__(self):
        self._base_dir = Path(settings.projects_dir)

    def _log_path(self, project_id: str) -> Path:
        d = self._base_dir / project_id / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / "llm_conversations.jsonl"

    def _log_path_full(self, project_id: str) -> Path:
        d = self._base_dir / project_id / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / "llm_conversations_full.jsonl"

    def record(self, entry: ConversationEntry) -> None:
        """Append a conversation entry to the project's log."""
        try:
            # Keep the existing truncated log for quick UI/API access.
            path = self._log_path(entry.project_id)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(truncate=True), ensure_ascii=False) + "\n")

            # Also write a full-fidelity log for debugging.
            full_path = self._log_path_full(entry.project_id)
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(truncate=False), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to log LLM conversation: %s", exc)

    def get_conversations(
        self, project_id: str, *, step: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Read conversation log for a project."""
        path = self._log_path(project_id)
        if not path.exists():
            return []

        entries = []
        try:
            for line in path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if step and entry.get("step") != step:
                    continue
                entries.append(entry)
        except Exception as exc:
            logger.warning("Failed to read LLM conversations: %s", exc)

        return entries[-limit:]

    def get_summary(self, project_id: str) -> Dict[str, Any]:
        """Get a summary of all LLM interactions for a project."""
        entries = self.get_conversations(project_id, limit=1000)
        if not entries:
            return {"total": 0, "steps": {}, "total_duration_ms": 0}

        steps: Dict[str, int] = {}
        total_duration = 0.0
        errors = 0
        for e in entries:
            s = e.get("step", "unknown")
            steps[s] = steps.get(s, 0) + 1
            total_duration += e.get("duration_ms", 0)
            if not e.get("success", True):
                errors += 1

        return {
            "total": len(entries),
            "steps": steps,
            "errors": errors,
            "total_duration_ms": round(total_duration, 1),
            "model": entries[-1].get("model", "unknown"),
        }


# Singleton
llm_conversation_logger = LLMConversationLogger()
