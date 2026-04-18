"""Benchmark helpers for baseline timing, comparison, and score trend history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from .baseline import deterministic_evidence, infer_task_with_openai
from .determinism import set_global_seed
from .tasks import grade_task, task_catalog


@dataclass(frozen=True)
class BenchmarkTaskResult:
    task_id: str
    score: float
    source: str
    elapsed_ms: float


@dataclass(frozen=True)
class BenchmarkReport:
    mode: str
    deterministic_seed: int
    average_score: float
    task_metrics: list[BenchmarkTaskResult]
    comparison: dict[str, Any]
    trend_history: list[dict[str, Any]]


def run_benchmark(
    *,
    client: Any | None = None,
    model: str | None = None,
    deterministic_seed: int = 42,
    history_file: str = "artifacts/score_trend_history.json",
    compare_modes: bool = True,
) -> BenchmarkReport:
    set_global_seed(deterministic_seed)

    deterministic_metrics = _benchmark_mode(
        mode="deterministic",
        client=None,
        model=None,
    )

    comparison: dict[str, Any] = {
        "deterministic": _compact_metrics(deterministic_metrics),
        "model": None,
        "delta_by_task": {},
    }

    selected_metrics = deterministic_metrics
    selected_mode = "deterministic"

    if client is not None and model:
        model_metrics = _benchmark_mode(mode="openai", client=client, model=model)
        comparison["model"] = _compact_metrics(model_metrics)

        if compare_modes:
            for item in deterministic_metrics:
                model_item = next((entry for entry in model_metrics if entry.task_id == item.task_id), None)
                if model_item is None:
                    continue
                comparison["delta_by_task"][item.task_id] = round(model_item.score - item.score, 6)

        selected_metrics = model_metrics
        selected_mode = "openai"

    average_score = sum(item.score for item in selected_metrics) / len(selected_metrics)
    trend_history = _append_score_history(
        history_file=history_file,
        entry={
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "mode": selected_mode,
            "deterministic_seed": deterministic_seed,
            "average_score": average_score,
        },
    )

    return BenchmarkReport(
        mode=selected_mode,
        deterministic_seed=deterministic_seed,
        average_score=average_score,
        task_metrics=selected_metrics,
        comparison=comparison,
        trend_history=trend_history,
    )


def _benchmark_mode(mode: str, client: Any | None, model: str | None) -> list[BenchmarkTaskResult]:
    metrics: list[BenchmarkTaskResult] = []
    for task in task_catalog():
        start = time.perf_counter()
        if mode == "openai" and client is not None and model:
            evidence = infer_task_with_openai(client, model, task.task_id, task.description)
            source = "openai"
        else:
            evidence = deterministic_evidence(task.task_id)
            source = "deterministic"

        score = grade_task(task.task_id, evidence)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.append(
            BenchmarkTaskResult(
                task_id=task.task_id,
                score=score,
                source=source,
                elapsed_ms=elapsed_ms,
            )
        )
    return metrics


def _append_score_history(history_file: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(history_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    else:
        history = []

    if not isinstance(history, list):
        history = []

    history.append(entry)
    history = history[-200:]
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return history


def _compact_metrics(items: list[BenchmarkTaskResult]) -> dict[str, Any]:
    average = sum(item.score for item in items) / len(items)
    return {
        "average_score": average,
        "tasks": [
            {
                "task_id": item.task_id,
                "score": item.score,
                "elapsed_ms": round(item.elapsed_ms, 4),
            }
            for item in items
        ],
    }
