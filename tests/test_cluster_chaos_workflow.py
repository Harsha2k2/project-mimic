from pathlib import Path

import yaml


def test_cluster_chaos_workflow_runs_fault_suite() -> None:
    workflow = Path(".github/workflows/cluster-chaos.yml")
    payload = yaml.safe_load(workflow.read_text(encoding="utf-8"))

    assert payload["name"] == "cluster-chaos"

    job = payload["jobs"]["cluster-chaos-tests"]
    step_names = [step["name"] for step in job["steps"] if "name" in step]

    assert "Install dependencies" in step_names
    assert "Run cluster chaos suite" in step_names

    run_step = next(step for step in job["steps"] if step.get("name") == "Run cluster chaos suite")
    assert "tests/test_cluster_chaos.py" in run_step["run"]
    assert "tests/test_reliability_chaos.py" in run_step["run"]
