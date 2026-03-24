from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TestDefinition(BaseModel):
    test_id: str
    prompt: str
    suite_content: str
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    project_context_id: Optional[str] = None
    preview_url_hint: Optional[str] = None
    project_type_hint: Optional[str] = None
    tech_stack_hint: list[str] = Field(default_factory=list)

    latest_test_cases: list[Dict[str, Any]] = Field(default_factory=list)
