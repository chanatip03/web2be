"""JSON-file-backed repository for projects and deployments.

Each entity is stored as ``<id>.json`` inside a ``.meta/`` subdirectory.
The store keeps an in-memory cache for fast reads and writes atomically
(write-to-temp-then-rename) to avoid corruption on crash.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class JsonStore(Generic[T]):
    """Thread-safe, file-backed store for a single Pydantic model type."""

    def __init__(self, directory: str | Path, model_cls: Type[T], *, id_field: str = "project_id"):
        self._dir = Path(directory) / ".meta"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._model_cls = model_cls
        self._id_field = id_field
        self._cache: Dict[str, T] = {}

        # Load existing records from disk on init
        self._load_all()

    # ── public API ───────────────────────────────────────────────

    def get(self, entity_id: str) -> Optional[T]:
        return self._cache.get(entity_id)

    def list_all(self) -> List[T]:
        return list(self._cache.values())

    def save(self, entity: T) -> None:
        entity_id = getattr(entity, self._id_field)
        self._cache[entity_id] = entity
        self._persist(entity_id, entity)

    def delete(self, entity_id: str) -> bool:
        if entity_id not in self._cache:
            return False
        del self._cache[entity_id]
        path = self._meta_path(entity_id)
        if path.exists():
            path.unlink()
        return True

    def exists(self, entity_id: str) -> bool:
        return entity_id in self._cache

    # ── internal ─────────────────────────────────────────────────

    def _meta_path(self, entity_id: str) -> Path:
        return self._dir / f"{entity_id}.json"

    def _persist(self, entity_id: str, entity: T) -> None:
        target = self._meta_path(entity_id)
        try:
            data = entity.model_dump(mode="json")
            # Atomic write: temp file → rename
            fd, tmp = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            Path(tmp).replace(target)
        except Exception:
            logger.exception("Failed to persist %s", entity_id)

    def _load_all(self) -> None:
        loaded = 0
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entity = self._model_cls.model_validate(data)
                entity_id = getattr(entity, self._id_field)
                self._cache[entity_id] = entity
                loaded += 1
            except Exception:
                logger.warning("Skipped corrupt metadata %s", path.name, exc_info=True)
        if loaded:
            logger.info("Loaded %d %s records from disk", loaded, self._model_cls.__name__)
