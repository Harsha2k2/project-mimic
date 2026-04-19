from pathlib import Path
from textwrap import dedent

from tools.observability import check_slo_burn_rate


def test_slo_burn_rate_check_warns_or_pages(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "slo-alerts.yml").write_text(
        dedent(
            """
            warning_burn_rate: 1.5
            paging_burn_rate: 2.0
            service_name: project-mimic-api
            on_call_target: sre-oncall
            """
        ).strip(),
        encoding="utf-8",
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "slo-burn-rate.json").write_text(
        '{"service_name": "project-mimic-api", "burn_rate": 1.6, "error_budget_remaining": 0.88}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert check_slo_burn_rate.main() == 1


def test_slo_burn_rate_check_passes_when_healthy(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "slo-alerts.yml").write_text(
        dedent(
            """
            warning_burn_rate: 1.5
            paging_burn_rate: 2.0
            service_name: project-mimic-api
            on_call_target: sre-oncall
            """
        ).strip(),
        encoding="utf-8",
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "slo-burn-rate.json").write_text(
        '{"service_name": "project-mimic-api", "burn_rate": 1.0, "error_budget_remaining": 0.99}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert check_slo_burn_rate.main() == 0