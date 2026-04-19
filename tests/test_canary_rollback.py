from pathlib import Path

from tools.deploy.check_canary_slo import main


def test_canary_slo_gate_passes_without_rollback(monkeypatch, tmp_path) -> None:
    report_dir = tmp_path / "artifacts"
    report_dir.mkdir()
    (report_dir / "canary-slo.json").write_text(
        """
        {
          "error_rate": 0.01,
          "p95_latency_ms": 120,
          "min_success_rate": 0.98,
          "max_p95_latency_ms": 700,
          "canary_namespace": "project-mimic",
          "canary_deployment": "mimic-control-plane-canary"
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main() == 0


def test_canary_slo_gate_rolls_back_on_breach(monkeypatch, tmp_path) -> None:
    report_dir = tmp_path / "artifacts"
    report_dir.mkdir()
    (report_dir / "canary-slo.json").write_text(
        """
        {
          "error_rate": 0.10,
          "p95_latency_ms": 900,
          "min_success_rate": 0.98,
          "max_p95_latency_ms": 700,
          "canary_namespace": "project-mimic",
          "canary_deployment": "mimic-control-plane-canary"
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    calls: list[list[str]] = []

    def fake_run(args, check):
        calls.append(list(args))
        return None

    monkeypatch.setattr("tools.deploy.check_canary_slo.subprocess.run", fake_run)

    assert main() == 1
    assert calls == [["kubectl", "-n", "project-mimic", "scale", "deployment", "mimic-control-plane-canary", "--replicas=0"]]