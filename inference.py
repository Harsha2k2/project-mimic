"""Baseline inference runner for Project Mimic tasks.

Environment variables:
- API_BASE_URL
- MODEL_NAME
- OPENAI_API_KEY (or HF_TOKEN fallback)
"""

from __future__ import annotations

import json
import os

from project_mimic.baseline import run_baseline


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
    client, model = _build_client()
    results = run_baseline(client=client, model=model)
    average = sum(item.score for item in results) / len(results)

    payload = {
        "mode": "openai" if client else "deterministic",
        "average_score": round(average, 4),
        "results": [
            {
                "task_id": item.task_id,
                "score": round(item.score, 4),
                "source": item.source,
            }
            for item in results
        ],
    }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
