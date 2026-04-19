import json

from tools.incident.runbook_automation import render_runbook


def test_render_runbook_for_known_incident_class() -> None:
    payload = render_runbook("triton_inference_error")

    assert payload["severity"] == "high"
    assert payload["owner"] == "ml-platform-oncall"
    assert any("TRITON_ENDPOINT" in step for step in payload["steps"])


def test_render_runbook_rejects_unknown_incident_class() -> None:
    try:
        render_runbook("unknown_incident")
    except KeyError as exc:
        assert "unknown incident class" in str(exc)
    else:
        raise AssertionError("expected KeyError")