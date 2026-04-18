import json
from pathlib import Path

from project_mimic.baseline import run_baseline


def test_deterministic_baseline_matches_snapshot() -> None:
    results = run_baseline(client=None, model=None)
    payload = {
        "average_score": sum(item.score for item in results) / len(results),
        "results": [
            {
                "task_id": item.task_id,
                "score": item.score,
                "source": item.source,
                "evidence": {
                    "search_submitted": item.evidence.search_submitted,
                    "offers_extracted": item.evidence.offers_extracted,
                    "sites_visited": item.evidence.sites_visited,
                    "constraints_satisfied": item.evidence.constraints_satisfied,
                    "cheapest_selected": item.evidence.cheapest_selected,
                    "steps_used": item.evidence.steps_used,
                    "max_steps": item.evidence.max_steps,
                },
            }
            for item in results
        ],
    }

    snapshot = json.loads(Path("tests/snapshots/baseline_deterministic_snapshot.json").read_text(encoding="utf-8"))

    assert payload["results"] == snapshot["results"]
    assert abs(payload["average_score"] - snapshot["average_score"]) < 1e-6
