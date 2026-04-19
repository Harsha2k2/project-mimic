from __future__ import annotations

import json
from pathlib import Path

import yaml

from project_mimic.benchmarking import run_benchmark


def main() -> int:
    thresholds_path = Path("config/performance-thresholds.yml")
    if not thresholds_path.exists():
        print("Performance thresholds missing")
        return 1

    thresholds = yaml.safe_load(thresholds_path.read_text(encoding="utf-8")) or {}
    min_average_score = float(thresholds.get("min_average_score", 0.99))
    max_task_elapsed_ms = float(thresholds.get("max_task_elapsed_ms", 1000.0))
    max_average_elapsed_ms = float(thresholds.get("max_average_elapsed_ms", 500.0))
    deterministic_seed = int(thresholds.get("deterministic_seed", 42))

    report = run_benchmark(deterministic_seed=deterministic_seed, compare_modes=False)
    report_path = Path("artifacts/performance-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "mode": report.mode,
                "deterministic_seed": report.deterministic_seed,
                "average_score": report.average_score,
                "task_metrics": [metric.__dict__ for metric in report.task_metrics],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    average_elapsed_ms = sum(metric.elapsed_ms for metric in report.task_metrics) / len(report.task_metrics)
    violations: list[str] = []
    if report.average_score < min_average_score:
        violations.append(
            f"average score {report.average_score:.4f} below minimum {min_average_score:.4f}"
        )
    if average_elapsed_ms > max_average_elapsed_ms:
        violations.append(
            f"average elapsed {average_elapsed_ms:.2f}ms exceeds {max_average_elapsed_ms:.2f}ms"
        )
    for metric in report.task_metrics:
        if metric.elapsed_ms > max_task_elapsed_ms:
            violations.append(
                f"task {metric.task_id} elapsed {metric.elapsed_ms:.2f}ms exceeds {max_task_elapsed_ms:.2f}ms"
            )

    if violations:
        for violation in violations:
            print(violation)
        return 1

    print("Capacity thresholds passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())