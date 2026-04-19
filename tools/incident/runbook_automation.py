from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNBOOKS: dict[str, dict[str, Any]] = {
    "api_session_conflict": {
        "severity": "medium",
        "owner": "api-oncall",
        "summary": "Session reached a terminal or conflicting state.",
        "steps": [
            "Confirm the session id and tenant scope.",
            "Inspect recent rollback or resume actions.",
            "Create a fresh session if the conflict is expected after completion.",
        ],
    },
    "checkpoint_missing": {
        "severity": "high",
        "owner": "platform-oncall",
        "summary": "Checkpoint store has no entry for the requested session.",
        "steps": [
            "Verify checkpoint store configuration.",
            "Confirm the session id and restore window.",
            "Rehydrate from backup if the checkpoint store is unavailable.",
        ],
    },
    "triton_inference_error": {
        "severity": "high",
        "owner": "ml-platform-oncall",
        "summary": "Triton inference endpoint failed or returned invalid payloads.",
        "steps": [
            "Check TRITON_ENDPOINT reachability.",
            "Review host allowlist and mTLS settings.",
            "Inspect Triton health and GPU capacity.",
        ],
    },
    "identity_rotation_thrash": {
        "severity": "medium",
        "owner": "security-oncall",
        "summary": "Identity rotation is happening too frequently.",
        "steps": [
            "Review risk inputs and thresholds.",
            "Inspect proxy health history and quarantine windows.",
            "Pause automation until the risk signal stabilizes.",
        ],
    },
    "flaky_ci": {
        "severity": "low",
        "owner": "ci-oncall",
        "summary": "A test or workflow is exhibiting timing-sensitive behavior.",
        "steps": [
            "Rerun the flaky-detection workflow.",
            "Check quarantine metadata and recent changes.",
            "File a follow-up issue if the failure reproduces.",
        ],
    },
}


def render_runbook(incident_class: str) -> dict[str, Any]:
    key = incident_class.strip().lower()
    if not key:
        raise ValueError("incident_class is required")

    runbook = RUNBOOKS.get(key)
    if runbook is None:
        raise KeyError(f"unknown incident class: {incident_class}")

    return {
        "incident_class": key,
        "severity": runbook["severity"],
        "owner": runbook["owner"],
        "summary": runbook["summary"],
        "steps": list(runbook["steps"]),
    }


def main() -> int:
    if len(list(Path.cwd().parts)) < 1:
        return 1

    import argparse

    parser = argparse.ArgumentParser(description="Render incident runbooks")
    parser.add_argument("incident_class")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        payload = render_runbook(args.incident_class)
    except (KeyError, ValueError) as exc:
        print(str(exc))
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Incident: {payload['incident_class']}")
        print(f"Severity: {payload['severity']}")
        print(f"Owner: {payload['owner']}")
        print(f"Summary: {payload['summary']}")
        print("Steps:")
        for step in payload["steps"]:
            print(f"- {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())