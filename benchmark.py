"""Benchmark runner for Project Mimic deterministic and model modes."""

from __future__ import annotations

import argparse
import json
import os

from project_mimic.benchmarking import run_benchmark


def _build_client() -> tuple[object | None, str | None]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("HF_TOKEN")
    model_name = os.getenv("MODEL_NAME")
    base_url = os.getenv("API_BASE_URL")

    if not api_key or not model_name:
        return None, None

    try:
        from openai import OpenAI
    except ImportError:
        return None, None

    kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs), model_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--history-file", default="artifacts/score_trend_history.json")
    parser.add_argument("--compare-modes", action="store_true")
    args = parser.parse_args()

    client, model = _build_client()
    report = run_benchmark(
        client=client,
        model=model,
        deterministic_seed=args.seed,
        history_file=args.history_file,
        compare_modes=args.compare_modes,
    )

    payload = {
        "mode": report.mode,
        "deterministic_seed": report.deterministic_seed,
        "average_score": round(report.average_score, 6),
        "task_metrics": [
            {
                "task_id": item.task_id,
                "score": round(item.score, 6),
                "source": item.source,
                "elapsed_ms": round(item.elapsed_ms, 4),
            }
            for item in report.task_metrics
        ],
        "comparison": report.comparison,
        "trend_history": report.trend_history,
    }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
