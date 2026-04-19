from pathlib import Path
from textwrap import dedent

from project_mimic.benchmarking import BenchmarkReport, BenchmarkTaskResult
from tools.performance import check_capacity


def test_capacity_gate_passes_within_thresholds(monkeypatch, tmp_path) -> None:
    thresholds_dir = tmp_path / "config"
    thresholds_dir.mkdir()
    (thresholds_dir / "performance-thresholds.yml").write_text(
        dedent(
            """
            min_average_score: 0.95
            max_task_elapsed_ms: 1000
            max_average_elapsed_ms: 800
            deterministic_seed: 99
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def fake_run_benchmark(*, deterministic_seed, compare_modes):
        return BenchmarkReport(
            mode="deterministic",
            deterministic_seed=deterministic_seed,
            average_score=0.99,
            task_metrics=[
                BenchmarkTaskResult(task_id="a", score=1.0, source="deterministic", elapsed_ms=10.0),
                BenchmarkTaskResult(task_id="b", score=0.98, source="deterministic", elapsed_ms=12.0),
            ],
            comparison={},
            trend_history=[],
        )

    monkeypatch.setattr(check_capacity, "run_benchmark", fake_run_benchmark)

    assert check_capacity.main() == 0
    assert (tmp_path / "artifacts" / "performance-report.json").exists()


def test_capacity_gate_fails_on_latency_breach(monkeypatch, tmp_path) -> None:
    thresholds_dir = tmp_path / "config"
    thresholds_dir.mkdir()
    (thresholds_dir / "performance-thresholds.yml").write_text(
        dedent(
            """
            min_average_score: 0.95
            max_task_elapsed_ms: 5
            max_average_elapsed_ms: 5
            deterministic_seed: 99
            """
        ).strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    def fake_run_benchmark(*, deterministic_seed, compare_modes):
        return BenchmarkReport(
            mode="deterministic",
            deterministic_seed=deterministic_seed,
            average_score=0.99,
            task_metrics=[
                BenchmarkTaskResult(task_id="a", score=1.0, source="deterministic", elapsed_ms=10.0),
            ],
            comparison={},
            trend_history=[],
        )

    monkeypatch.setattr(check_capacity, "run_benchmark", fake_run_benchmark)

    assert check_capacity.main() == 1