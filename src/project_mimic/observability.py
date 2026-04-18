"""Minimal observability helpers for local and CI validation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class InMemoryMetrics:
    request_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency_ms_totals: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        self.request_counts[path] += 1
        self.status_counts[str(status_code)] += 1
        self.latency_ms_totals[path] += duration_ms

    def snapshot(self) -> dict:
        average_latency_ms = {}
        for path, count in self.request_counts.items():
            total = self.latency_ms_totals[path]
            average_latency_ms[path] = round(total / count, 4) if count else 0.0

        return {
            "requests": dict(self.request_counts),
            "status_codes": dict(self.status_counts),
            "average_latency_ms": average_latency_ms,
        }
