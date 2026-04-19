from pathlib import Path

from project_mimic.deploy_overlays import load_yaml_dict, render_overlay


def test_browser_worker_template_exposes_cross_engine_env_vars() -> None:
    template = Path("deploy/helm/project-mimic/templates/browser-worker-deployment.yaml")
    content = template.read_text(encoding="utf-8")

    assert "PLAYWRIGHT_BROWSERS" in content
    assert "PLAYWRIGHT_PRIMARY_BROWSER" in content
    assert "join" in content
    assert ".Values.browserWorker.engines" in content
    assert "index .Values.browserWorker.engines 0" in content


def test_default_values_include_multiple_browser_engines() -> None:
    rendered = load_yaml_dict("deploy/helm/project-mimic/values.yaml")

    assert rendered["browserWorker"]["engines"] == ["chromium", "firefox", "webkit"]


def test_dev_overlay_retains_broader_engine_coverage() -> None:
    rendered = render_overlay(
        "deploy/helm/project-mimic/values.yaml",
        "deploy/helm/project-mimic/values-dev.yaml",
    )

    assert rendered["browserWorker"]["engines"] == ["chromium", "firefox"]


def test_prod_overlay_retains_full_cross_browser_engine_set() -> None:
    rendered = render_overlay(
        "deploy/helm/project-mimic/values.yaml",
        "deploy/helm/project-mimic/values-prod.yaml",
    )

    assert rendered["browserWorker"]["engines"] == ["chromium", "firefox", "webkit"]
