"""Prompt-based test generator — user describes what to test,
LLM generates Robot Framework test suites."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.deployment.core.config import settings
from app.deployment.services.llm.client import llm_client
from app.deployment.services.llm.parser import extract_text_content
from app.deployment.services.logger import LoggerManager

logger = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────

TEST_GEN_SYSTEM = """\
You are a QA engineer expert in Robot Framework.
The user will describe what tests they need. Generate a complete Robot Framework
test suite (.robot file) based on their description.

Requirements:
- Use Robot Framework syntax
- Include *** Settings ***, *** Variables ***, *** Test Cases ***, and *** Keywords *** sections
- Use SeleniumLibrary for UI tests and RequestsLibrary for API tests
- Each test case must have clear documentation
- Include sensible default variables (URL, browser, etc.)
- Make tests runnable out of the box

Output ONLY the .robot file content — no markdown fences, no explanation.
"""

TEST_GEN_USER = """\
## Project info
- Project ID: {project_id}
- Project type: {project_type}
- Tech stack: {tech_stack}
- Preview URL: {preview_url}

## User's testing requirements
{user_prompt}
"""

# ── Test case model ──────────────────────────────────────────────

TEST_LIST_SYSTEM = """\
You are a QA engineer. The user will describe their testing needs.
Return a JSON array of test case objects, each with:
{
  "name": "descriptive test name",
  "description": "what this test verifies",
  "test_type": "ui" | "api" | "integration",
  "keywords": ["step1", "step2"],
  "target_url": "URL path to test",
  "expected_status_code": 200
}

Return ONLY the JSON array — no fences, no explanation.
"""


async def generate_test_cases(
    project_id: str,
    user_prompt: str,
    *,
    project_type: str = "unknown",
    tech_stack: List[str] | None = None,
    preview_url: str = "",
) -> List[Dict[str, Any]]:
    """Generate test case descriptions from user prompt via LLM."""
    proj_logger = LoggerManager.get(project_id)
    proj_logger.log_llm_request("test_cases", user_prompt)

    user_msg = TEST_GEN_USER.format(
        project_id=project_id,
        project_type=project_type,
        tech_stack=", ".join(tech_stack or []),
        preview_url=preview_url or "http://localhost:3000",
        user_prompt=user_prompt,
    )

    try:
        raw = await llm_client.analyze(TEST_LIST_SYSTEM, user_msg)
        proj_logger.log_llm_response("test_cases", raw, success=True)

        # Parse JSON array
        from app.deployment.services.llm.parser import strip_code_fences
        clean = strip_code_fences(raw)
        try:
            cases = json.loads(clean)
            if isinstance(cases, list):
                proj_logger.log_test_gen(len(cases), user_prompt)
                return cases
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract array
        import re
        match = re.search(r"\[.*\]", clean, re.DOTALL)
        if match:
            cases = json.loads(match.group())
            if isinstance(cases, list):
                proj_logger.log_test_gen(len(cases), user_prompt)
                return cases

        return []

    except Exception as exc:
        proj_logger.log_llm_response("test_cases", "", success=False, error=str(exc))
        raise


async def generate_robot_suite(
    project_id: str,
    user_prompt: str,
    *,
    project_type: str = "unknown",
    tech_stack: List[str] | None = None,
    preview_url: str = "",
) -> str:
    """Generate a complete .robot test suite from user's description."""
    proj_logger = LoggerManager.get(project_id)
    proj_logger.log_llm_request("robot_suite", user_prompt)

    user_msg = TEST_GEN_USER.format(
        project_id=project_id,
        project_type=project_type,
        tech_stack=", ".join(tech_stack or []),
        preview_url=preview_url or "http://localhost:3000",
        user_prompt=user_prompt,
    )

    try:
        raw = await llm_client.generate(TEST_GEN_SYSTEM, user_msg)
        suite_content = extract_text_content(raw)
        proj_logger.log_llm_response("robot_suite", suite_content, success=True)

        # Save to project directory
        suite_dir = Path(settings.projects_dir) / project_id / "tests"
        suite_dir.mkdir(parents=True, exist_ok=True)
        suite_path = suite_dir / "test_suite.robot"
        suite_path.write_text(suite_content, encoding="utf-8")

        logger.info("Generated test suite for %s (%d chars)", project_id, len(suite_content))
        return suite_content

    except Exception as exc:
        proj_logger.log_llm_response("robot_suite", "", success=False, error=str(exc))
        raise


async def generate_robot_suite_content(
    *,
    context_id: str,
    user_prompt: str,
    project_type: str = "unknown",
    tech_stack: List[str] | None = None,
    preview_url: str = "",
) -> str:
    """Generate Robot suite content without persisting to a project path."""
    proj_logger = LoggerManager.get(context_id)
    proj_logger.log_llm_request("robot_suite", user_prompt)

    user_msg = TEST_GEN_USER.format(
        project_id=context_id,
        project_type=project_type,
        tech_stack=", ".join(tech_stack or []),
        preview_url=preview_url or "http://localhost:3000",
        user_prompt=user_prompt,
    )

    try:
        raw = await llm_client.generate(TEST_GEN_SYSTEM, user_msg)
        suite_content = extract_text_content(raw)
        proj_logger.log_llm_response("robot_suite", suite_content, success=True)
        logger.info("Generated test suite content for %s (%d chars)", context_id, len(suite_content))
        return suite_content
    except Exception as exc:
        proj_logger.log_llm_response("robot_suite", "", success=False, error=str(exc))
        raise
