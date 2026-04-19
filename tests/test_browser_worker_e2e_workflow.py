from pathlib import Path

import yaml


def test_browser_worker_e2e_workflow_contains_kind_and_integration_tests() -> None:
    workflow = Path(".github/workflows/browser-worker-e2e.yml")
    payload = yaml.safe_load(workflow.read_text(encoding="utf-8"))

    assert payload["name"] == "browser-worker-e2e"
    job = payload["jobs"]["browser-worker-integration"]
    step_names = [step["name"] for step in job["steps"] if "name" in step]

    assert "Setup kind" in step_names
    assert "Install Project Mimic chart" in step_names
    assert "Run integration tests" in step_names

    install_step = next(step for step in job["steps"] if step.get("name") == "Install Project Mimic chart")
    assert "--set triton.replicas=0" in install_step["run"]
