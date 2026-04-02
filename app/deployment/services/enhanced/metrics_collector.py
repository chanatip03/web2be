"""Metrics collector — tracks deployment, LLM, and Docker operation metrics."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List


class MetricsCollector:
    """In-memory metrics tracking for system observability."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._timers: Dict[str, List[float]] = defaultdict(list)
        self._events: List[Dict[str, Any]] = []
        self._start_time = datetime.now()

    # ── Counters ─────────────────────────────────────────────────

    def increment(self, name: str, amount: int = 1):
        self._counters[name] += amount

    # ── Timers ───────────────────────────────────────────────────

    def record_duration(self, name: str, duration: float):
        self._timers[name].append(duration)
        # Keep only last 100 measurements
        if len(self._timers[name]) > 100:
            self._timers[name] = self._timers[name][-100:]

    def time_it(self, name: str):
        """Context manager for timing operations."""
        return _Timer(self, name)

    # ── Events ───────────────────────────────────────────────────

    def record_event(self, event_type: str, data: Dict[str, Any] | None = None):
        self._events.append({
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data or {},
        })
        # Keep only last 500 events
        if len(self._events) > 500:
            self._events = self._events[-500:]

    # ── Report ───────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        timer_stats = {}
        for name, durations in self._timers.items():
            if durations:
                timer_stats[name] = {
                    "count": len(durations),
                    "avg_ms": round(sum(durations) / len(durations) * 1000, 1),
                    "min_ms": round(min(durations) * 1000, 1),
                    "max_ms": round(max(durations) * 1000, 1),
                }

        return {
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            "counters": dict(self._counters),
            "timers": timer_stats,
            "recent_events": self._events[-20:],
        }


class _Timer:
    def __init__(self, collector: MetricsCollector, name: str):
        self._collector = collector
        self._name = name
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        duration = time.perf_counter() - self._start
        self._collector.record_duration(self._name, duration)


metrics = MetricsCollector()
