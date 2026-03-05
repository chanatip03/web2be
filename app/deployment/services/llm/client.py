"""Lightning AI chat-completions client with thinking/reasoning support.

Uses the exact API format the user specified, with retry + exponential backoff.
All LLM interactions are recorded by the conversation logger for debugging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
import weakref
from typing import Any, Dict, List, Optional

import httpx

from app.deployment.core.config import settings
from app.deployment.core.exceptions import LLMError
from app.deployment.services.llm.parser import extract_json, strip_code_fences
from app.deployment.services.logger import LoggerManager

logger = logging.getLogger(__name__)


def _parse_retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse Retry-After header if present.

    Retry-After can be an int seconds or an HTTP date; we only support seconds.
    """
    try:
        ra = resp.headers.get("retry-after")
        if not ra:
            return None
        return float(ra.strip())
    except Exception:
        return None


_GLOBAL_LLM_SEM_LOCK = threading.Lock()
_GLOBAL_LLM_SEM: threading.Semaphore | None = None
_GLOBAL_LLM_SEM_LIMIT: int | None = None


def _get_global_llm_semaphore() -> threading.Semaphore:
    """A process-wide semaphore to serialize LLM calls across threads/event loops."""
    global _GLOBAL_LLM_SEM, _GLOBAL_LLM_SEM_LIMIT
    limit = max(1, int(getattr(settings, "llm_max_concurrency", 1) or 1))
    with _GLOBAL_LLM_SEM_LOCK:
        if _GLOBAL_LLM_SEM is None or _GLOBAL_LLM_SEM_LIMIT != limit:
            _GLOBAL_LLM_SEM = threading.Semaphore(limit)
            _GLOBAL_LLM_SEM_LIMIT = limit
        return _GLOBAL_LLM_SEM

# Active project context for conversation logging
_current_project_id: Optional[str] = None


def set_active_project(project_id: Optional[str]) -> None:
    """Set the current project context for conversation logging."""
    global _current_project_id
    _current_project_id = project_id


class LLMClient:
    """Async client for Lightning AI chat completions."""

    # Semaphore must not be shared across event loops (Python 3.11+ binds
    # asyncio primitives to the loop that first uses them). Our deployment
    # pipeline runs in background threads via `asyncio.run()`, creating
    # separate loops. Keep one semaphore per running loop.
    _semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = weakref.WeakKeyDictionary()

    def __init__(self) -> None:
        self.api_url = settings.litai_api_url
        self.api_key = settings.litai_api_key
        self.model = settings.litai_model
        self.timeout = settings.llm_timeout_seconds
        self.max_tokens = settings.llm_max_output_tokens
        self.max_retries = settings.llm_max_retries
        self.backoff = settings.llm_retry_backoff

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        limit = max(1, int(getattr(settings, "llm_max_concurrency", 1) or 1))
        loop = asyncio.get_running_loop()
        sem = cls._semaphores.get(loop)
        if sem is None or getattr(sem, "_deployer_limit", None) != limit:
            sem = asyncio.Semaphore(limit)
            setattr(sem, "_deployer_limit", limit)
            cls._semaphores[loop] = sem
        return sem

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        ascii_chars = 0
        non_ascii_chars = 0
        for ch in text:
            if ord(ch) < 128:
                ascii_chars += 1
            else:
                non_ascii_chars += 1
        est = (ascii_chars / 4.0) + (non_ascii_chars / 2.0)
        return int(est) + 1

    def _min_json(self, obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        except Exception:
            return str(obj)

    # ── core chat ────────────────────────────────────────────────

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        step: str = "chat",
    ) -> str:
        """Send a chat completion request to Lightning AI.

        Messages are converted to the multipart content format that
        the API expects.  Thinking/reasoning is always enabled.
        """
        if not self.api_key:
            raise LLMError("LITAI_API_KEY is not set — check your .env file")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Format messages to content-array style
        formatted = []
        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "user")
            if isinstance(content, str):
                formatted.append({
                    "role": role,
                    "content": [{"type": "text", "text": content}],
                })
            elif isinstance(content, list):
                formatted.append({"role": role, "content": content})
            else:
                formatted.append({
                    "role": role,
                    "content": [{"type": "text", "text": str(content)}],
                })

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted,
            "temperature": temperature,
            "max_tokens": max_tokens or self.max_tokens,
            # Enable thinking / reasoning
            "reasoning": {"effort": "high"},
        }

        prompt_text = self._min_json(formatted)
        prompt_tokens_est = self._estimate_tokens(prompt_text)
        self._log_llm_request(step, prompt_text, prompt_tokens_est, payload.get("max_tokens"))

        # Extract prompts for logging
        system_prompt = ""
        user_prompt = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
            elif msg.get("role") == "user":
                user_prompt = msg.get("content", "")

        t0 = time.perf_counter()

        # Retry loop with exponential backoff
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Serialize across all deployment background threads.
                global_sem = _get_global_llm_semaphore()
                await asyncio.to_thread(global_sem.acquire)
                try:
                    async with self._get_semaphore():
                        async with httpx.AsyncClient(timeout=self.timeout) as client:
                            resp = await client.post(self.api_url, headers=headers, json=payload)
                            resp.raise_for_status()
                            data = resp.json()
                finally:
                    try:
                        global_sem.release()
                    except Exception:
                        pass

                choices = data.get("choices", [])
                if not choices:
                    raise LLMError(f"Empty choices in LLM response: {data}")

                response_text = choices[0]["message"]["content"]
                duration_ms = (time.perf_counter() - t0) * 1000

                usage = data.get("usage") if isinstance(data, dict) else None
                prompt_tokens = None
                completion_tokens = None
                total_tokens = None
                if isinstance(usage, dict):
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    total_tokens = usage.get("total_tokens")

                self._log_llm_response(
                    step,
                    response_text,
                    True,
                    "",
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )

                # Log successful conversation
                self._log_conversation(
                    step=step,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response=response_text,
                    request_payload=payload,
                    response_json=data if isinstance(data, dict) else {"raw": data},
                    temperature=temperature,
                    duration_ms=duration_ms,
                    success=True,
                    prompt_tokens_est=prompt_tokens_est,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    max_tokens=payload.get("max_tokens"),
                )

                return response_text

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_error = LLMError(
                    f"Lightning AI returned {status}: "
                    f"{exc.response.text[:500]}"
                )
                logger.warning("LLM attempt %d/%d failed: %s", attempt, self.max_retries, last_error)

                if attempt < self.max_retries:
                    # For 429, prefer Retry-After when present.
                    retry_after = _parse_retry_after_seconds(exc.response) if status == 429 else None
                    base_wait = self.backoff * (2 ** (attempt - 1))
                    wait = max(base_wait, retry_after or 0.0)
                    # Small jitter to avoid thundering herd.
                    wait = wait + random.uniform(0.0, 0.5)
                    logger.info("Retrying in %.1fs…", wait)
                    await asyncio.sleep(wait)
                    continue
            except httpx.TimeoutException:
                last_error = LLMError(f"LLM request timed out after {self.timeout}s")
                logger.warning("LLM attempt %d/%d timed out", attempt, self.max_retries)
            except Exception as exc:
                last_error = LLMError(f"LLM communication error: {exc}")
                logger.warning("LLM attempt %d/%d error: %s", attempt, self.max_retries, exc)

            if attempt < self.max_retries:
                wait = self.backoff * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
                logger.info("Retrying in %.1fs…", wait)
                await asyncio.sleep(wait)

        # Log failed conversation
        duration_ms = (time.perf_counter() - t0) * 1000
        self._log_llm_response(
            step,
            "",
            False,
            str(last_error),
            None,
            None,
            None,
        )

        self._log_conversation(
            step=step,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response="",
            request_payload=payload,
            response_json=None,
            temperature=temperature,
            duration_ms=duration_ms,
            success=False,
            error=str(last_error),
            prompt_tokens_est=prompt_tokens_est,
            max_tokens=payload.get("max_tokens"),
        )

        raise last_error or LLMError("LLM request failed after all retries")

    def _log_conversation(self, **kwargs) -> None:
        """Record conversation to the logger if a project context is set."""
        project_id = _current_project_id
        if not project_id:
            return
        try:
            from app.deployment.services.llm.conversation_logger import (
                ConversationEntry,
                llm_conversation_logger,
            )
            entry = ConversationEntry(
                project_id=project_id,
                model=self.model,
                **kwargs,
            )
            llm_conversation_logger.record(entry)
        except Exception as exc:
            logger.debug("Failed to log LLM conversation: %s", exc)

    def _log_llm_request(
        self,
        step: str,
        prompt_text: str,
        prompt_tokens_est: int,
        max_tokens: Optional[int],
    ) -> None:
        project_id = _current_project_id
        if not project_id:
            return
        try:
            proj_logger = LoggerManager.get(project_id)
            proj_logger.log_llm_request(
                task=step,
                prompt=prompt_text,
                model=self.model,
                prompt_tokens_est=prompt_tokens_est,
                max_tokens=max_tokens,
            )
        except Exception:
            pass

    def _log_llm_response(
        self,
        step: str,
        response_text: str,
        success: bool,
        error: str,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        total_tokens: Optional[int],
    ) -> None:
        project_id = _current_project_id
        if not project_id:
            return
        try:
            proj_logger = LoggerManager.get(project_id)
            proj_logger.log_llm_response(
                task=step,
                response=response_text,
                success=success,
                error=error,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except Exception:
            pass

    # ── task-specific helpers ────────────────────────────────────

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Run an analysis prompt and return the raw LLM text."""
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            step="analysis",
        )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Run a generation prompt (Dockerfile, build-spec, compose)."""
        return await self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            step="generation",
        )

    async def analyze_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Run analysis and parse result as JSON, with fence-stripping."""
        raw = await self.analyze(system_prompt, user_prompt)
        return extract_json(raw)


# Lazy singleton
llm_client = LLMClient()
