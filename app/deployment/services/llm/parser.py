"""Utilities for parsing LLM output — JSON extraction, fence stripping, etc."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) wrapping actual content."""
    if not text:
        return ""
    # Try to strip leading/trailing fences
    stripped = re.sub(r"^```(?:json|ya?ml|dockerfile|text)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()


def extract_json(text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON object from LLM output.

    Handles:
    - Clean JSON
    - JSON wrapped in code fences
    - JSON preceded/followed by explanatory text
    """
    if not text:
        return {}

    # 1. Try direct parse
    clean = strip_code_fences(text)
    try:
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2. Find first { … } block
    match = re.search(r"\{", clean)
    if match:
        start = match.start()
        depth = 0
        for i in range(start, len(clean)):
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = clean[start : i + 1]
                    try:
                        result = json.loads(candidate)
                        if isinstance(result, dict):
                            return result
                    except json.JSONDecodeError:
                        pass
                    break

    # 3. If standard matches fail, try to fix truncation by appending closing braces
    if match:
        start = match.start()
        candidate = clean[start:]
        open_braces = candidate.count("{")
        close_braces = candidate.count("}")
        missing = max(0, open_braces - close_braces)
        
        # Try appending missing braces + some padding
        for extra in range(missing, missing + 5):
            # Try directly
            try:
                res = json.loads(candidate + "}" * extra)
                if isinstance(res, dict):
                    return res
            except json.JSONDecodeError:
                pass
            
            # Try closing an open string first
            try:
                res = json.loads(candidate + '"' + "}" * extra)
                if isinstance(res, dict):
                    return res
            except json.JSONDecodeError:
                pass
                
            # Try closing an open array
            try:
                res = json.loads(candidate + ']' + "}" * extra)
                if isinstance(res, dict):
                    return res
            except json.JSONDecodeError:
                pass
            
            # Try closing literal values like null, true, false
            try:
                # remove trailing incomplete text up to last comma or colon
                last_comma = candidate.rfind(",")
                last_colon = candidate.rfind(":")
                cut_idx = max(last_comma, last_colon)
                if cut_idx > 0:
                    res = json.loads(candidate[:cut_idx] + "}" * extra)
                    if isinstance(res, dict):
                        return res
            except json.JSONDecodeError:
                pass

    logger.warning("Failed to extract JSON from LLM output (length=%d)", len(text))
    return {}


def extract_text_content(text: str) -> str:
    """Strip code fences and return clean text (for Dockerfile output)."""
    return strip_code_fences(text)
