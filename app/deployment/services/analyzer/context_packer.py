"""Context packer — reduce token count while preserving essential information."""

from __future__ import annotations

import re
from typing import Dict


def pack_context(files: Dict[str, str], *, max_total_chars: int = 30000) -> Dict[str, str]:
    """Compact file contents to fit within a token budget.

    Applies these transformations:
    - Remove excessive blank lines
    - Remove single-line comments
    - Truncate long files
    - Prioritise important files
    """
    packed: Dict[str, str] = {}
    char_budget = max_total_chars

    for path, content in files.items():
        if char_budget <= 0:
            break
        compacted = _compact(content)
        if len(compacted) > char_budget:
            compacted = compacted[:char_budget] + "\n...(truncated)"
        packed[path] = compacted
        char_budget -= len(compacted)

    return packed


def _compact(text: str) -> str:
    """Aggressively compact source code while preserving structure."""
    # Remove multi-line docstrings (Python)
    text = re.sub(r'"""[\s\S]*?"""', '"""..."""', text)
    text = re.sub(r"'''[\s\S]*?'''", "'''...'''", text)

    # Remove single-line comments (keep shebangs and pragmas)
    lines = text.split("\n")
    kept = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines (compress to max 1)
        if not stripped:
            if kept and kept[-1].strip() == "":
                continue
            kept.append("")
            continue
        # Skip comment-only lines (but keep #! and # type: etc)
        if stripped.startswith("#") and not stripped.startswith("#!") and "type:" not in stripped:
            continue
        # Skip JS/TS comment-only lines
        if stripped.startswith("//"):
            continue
        kept.append(line)

    return "\n".join(kept).strip()


def pack_file(path: str, content: str, *, max_chars: int = 3000) -> str:
    """Compact a single file."""
    compacted = _compact(content)
    if len(compacted) > max_chars:
        return compacted[:max_chars] + f"\n...(truncated, {len(content)} total)"
    return compacted
