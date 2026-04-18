"""Minimal observability helpers for local and CI validation."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import time
from typing import Any, Iterator
from uuid import uuid4


@dataclass(frozen=True)
class TraceSpan:
    trace_id: str
    span_id: str
    name: str
    component: str
    start_ms: float
    end_ms: float
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)


class OpenTelemetryTracer:
    """OpenTelemetry-compatible tracer with in-memory fallback span capture."""

    def __init__(self, component: str) -> None:
        self.component = component
        self._spans: list[TraceSpan] = []
        self._otel_tracer = self._try_build_otel_tracer(component)

    @staticmethod
    def _try_build_otel_tracer(component: str):
        try:
            from opentelemetry import trace
        except Exception:
            return None

        return trace.get_tracer(f"project_mimic.{component}")

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        span_trace_id = trace_id or str(uuid4())
        span_id = str(uuid4())
        attrs = dict(attributes or {})
        start = time.perf_counter()

        if self._otel_tracer is not None:
            with self._otel_tracer.start_as_current_span(name) as span:
                for key, value in attrs.items():
                    span.set_attribute(key, value)
                yield span_id
        else:
            yield span_id

        end = time.perf_counter()
        duration_ms = (end - start) * 1000.0
        self._spans.append(
            TraceSpan(
                trace_id=span_trace_id,
                span_id=span_id,
                name=name,
                component=self.component,
                start_ms=start * 1000.0,
                end_ms=end * 1000.0,
                duration_ms=duration_ms,
                attributes=attrs,
            )
        )

    def spans(self) -> list[TraceSpan]:
        return list(self._spans)

    def trace_snapshot(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "span_count": len(self._spans),
            "spans": [
                {
                    "trace_id": span.trace_id,
                    "span_id": span.span_id,
                    "name": span.name,
                    "duration_ms": round(span.duration_ms, 4),
                    "attributes": span.attributes,
                }
                for span in self._spans
            ],
        }


@dataclass
class InMemoryMetrics:
    request_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency_ms_totals: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    latency_samples_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    feature_attempt_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    feature_success_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    goal_action_correlation: dict[str, list[dict[str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    trace_links: dict[str, dict[str, str]] = field(default_factory=dict)

    def record(self, path: str, status_code: int, duration_ms: float) -> None:
        self.request_counts[path] += 1
        self.status_counts[str(status_code)] += 1
        self.latency_ms_totals[path] += duration_ms
        samples = self.latency_samples_ms[path]
        samples.append(duration_ms)
        if len(samples) > 5000:
            del samples[:-5000]

    def record_feature_result(
        self,
        feature: str,
        *,
        success: bool,
        trace_id: str | None = None,
        goal: str | None = None,
        action_type: str | None = None,
    ) -> None:
        self.feature_attempt_counts[feature] += 1
        if success:
            self.feature_success_counts[feature] += 1

        if trace_id and goal and action_type:
            self.goal_action_correlation[goal].append(
                {
                    "trace_id": trace_id,
                    "action_type": action_type,
                    "feature": feature,
                }
            )
            self.trace_links[trace_id] = {"goal": goal, "action_type": action_type}

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float:
        if not samples:
            return 0.0

        ordered = sorted(samples)
        rank = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
        return ordered[rank]

    def _latency_percentiles(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for path, samples in self.latency_samples_ms.items():
            out[path] = {
                "p95": round(self._percentile(samples, 95), 4),
                "p99": round(self._percentile(samples, 99), 4),
                "count": float(len(samples)),
            }
        return out

    def _feature_success_rates(self) -> dict[str, float]:
        rates: dict[str, float] = {}
        for feature, attempts in self.feature_attempt_counts.items():
            success = self.feature_success_counts.get(feature, 0)
            rates[feature] = round(success / attempts, 4) if attempts else 0.0
        return rates

    def snapshot(self) -> dict:
        average_latency_ms = {}
        for path, count in self.request_counts.items():
            total = self.latency_ms_totals[path]
            average_latency_ms[path] = round(total / count, 4) if count else 0.0

        return {
            "requests": dict(self.request_counts),
            "status_codes": dict(self.status_counts),
            "average_latency_ms": average_latency_ms,
            "latency_percentiles_ms": self._latency_percentiles(),
            "feature_success_rates": self._feature_success_rates(),
            "dashboards": {
                "endpoint_latency": self._latency_percentiles(),
                "feature_success": self._feature_success_rates(),
            },
            "goal_action_correlation": {
                goal: list(events) for goal, events in self.goal_action_correlation.items()
            },
            "trace_links": dict(self.trace_links),
        }
