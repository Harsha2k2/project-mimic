import json
import subprocess
import sys


def test_inference_main_runs_in_deterministic_mode_without_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)

    completed = subprocess.run(
        [sys.executable, "inference.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0

    payload = json.loads(completed.stdout)

    assert payload["mode"] == "deterministic"
    assert "average_score" in payload
    assert len(payload["results"]) == 3
