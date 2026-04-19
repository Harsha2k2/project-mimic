from pathlib import Path

import yaml


def test_triton_gpu_integration_workflow_targets_gpu_runner() -> None:
    workflow = Path(".github/workflows/triton-gpu-integration.yml")
    payload = yaml.safe_load(workflow.read_text(encoding="utf-8"))

    job = payload["jobs"]["triton-gpu-path"]
    assert job["runs-on"] == ["self-hosted", "gpu"]

    step_names = [step["name"] for step in job["steps"] if "name" in step]
    assert "Validate Triton integration path" in step_names
