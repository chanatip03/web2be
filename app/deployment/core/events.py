"""Simple in-process event bus for decoupled step notifications.

Usage:
    from app.deployment.core.events import event_bus

    # Subscribe
    async def on_step(data):
        print(data)
    event_bus.subscribe("deploy.step", on_step)

    # Publish
    await event_bus.publish("deploy.step", {"step": "building", "message": "..."})
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger("events")

Listener = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Lightweight async pub/sub within a single process."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def subscribe(self, event: str, listener: Listener) -> None:
        self._listeners[event].append(listener)

    def unsubscribe(self, event: str, listener: Listener) -> None:
        try:
            self._listeners[event].remove(listener)
        except ValueError:
            pass

    async def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        for listener in self._listeners.get(event, []):
            try:
                await listener(data or {})
            except Exception:
                logger.exception("Event listener error for %s", event)


event_bus = EventBus()
