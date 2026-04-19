from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.release_readiness import JsonFileReleaseReadinessStore, ReleaseReadinessService


def test_release_readiness_scorecard_generation_from_ci_evidence(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "operator-key:tenant-a")

    client = TestClient(create_app())

    generated = client.post(
        "/api/v1/release/readiness/scorecards/rc-2026-04-19",
        headers={"X-API-Key": "operator-key"},
        json={
            "release_id": "v1.8.0-rc1",
            "generated_by": "ci-release-pipeline",
            "minimum_pass_ratio": 0.75,
            "gate_weights": {
                "unit_tests": 1.0,
                "integration_tests": 1.4,
                "security_scan": 1.6,
                "perf_gate": 1.2,
            },
            "ci_evidence": [
                {
                    "gate_name": "unit_tests",
                    "status": "pass",
                    "required": True,
                    "critical": False,
                    "details": {"passed": "321"},
                },
                {
                    "gate_name": "integration_tests",
                    "status": "pass",
                    "required": True,
                    "critical": False,
                    "details": {"lane": "real-browser"},
                },
                {
                    "gate_name": "security_scan",
                    "status": "pass",
                    "required": True,
                    "critical": True,
                    "details": {"critical_cves": "0"},
                },
                {
                    "gate_name": "perf_gate",
                    "status": "warn",
                    "required": False,
                    "critical": False,
                    "details": {"p95_ms": "245"},
                },
            ],
        },
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["release_id"] == "v1.8.0-rc1"
    assert payload["release_blocked"] is False
    assert payload["overall_status"] in {"ready", "needs_review"}
    assert payload["score"] > 0

    listed = client.get(
        "/api/v1/release/readiness/scorecards",
        headers={"X-API-Key": "operator-key"},
        params={"release_id": "v1.8.0-rc1"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    fetched = client.get(
        "/api/v1/release/readiness/scorecards/rc-2026-04-19",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["scorecard_id"] == "rc-2026-04-19"


def test_release_readiness_blocked_by_critical_ci_failure_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    forbidden = client.post(
        "/api/v1/release/readiness/scorecards/rc-crit-fail",
        headers={"X-API-Key": "viewer-key"},
        json={
            "release_id": "v1.8.0-rc2",
            "generated_by": "viewer",
            "ci_evidence": [
                {"gate_name": "unit_tests", "status": "pass", "required": True, "critical": False},
            ],
        },
    )
    assert forbidden.status_code == 403

    legacy_generated = client.post(
        "/release/readiness/scorecards/rc-crit-fail",
        headers={"X-API-Key": "operator-key"},
        json={
            "release_id": "v1.8.0-rc2",
            "generated_by": "ci-release-pipeline",
            "minimum_pass_ratio": 0.9,
            "ci_evidence": [
                {
                    "gate_name": "security_scan",
                    "status": "fail",
                    "required": True,
                    "critical": True,
                    "details": {"critical_cves": "2"},
                },
                {
                    "gate_name": "unit_tests",
                    "status": "pass",
                    "required": True,
                    "critical": False,
                    "details": {"passed": "321"},
                },
            ],
        },
    )
    assert legacy_generated.status_code == 200
    assert legacy_generated.headers.get("Deprecation") == "true"

    payload = legacy_generated.json()
    assert payload["release_blocked"] is True
    assert payload["overall_status"] == "blocked"
    assert payload["critical_failure_count"] == 1

    legacy_get = client.get(
        "/release/readiness/scorecards/rc-crit-fail",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_get.status_code == 200
    assert legacy_get.headers.get("Deprecation") == "true"


def test_json_file_release_readiness_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "release-readiness.json"
    service = ReleaseReadinessService(store=JsonFileReleaseReadinessStore(str(store_path)))

    scorecard = service.generate_scorecard(
        tenant_id="tenant-a",
        scorecard_id="rc-2026-04-19",
        release_id="v1.8.0-rc1",
        generated_by="ci-release-pipeline",
        minimum_pass_ratio=0.8,
        gate_weights={"unit_tests": 1.0, "security_scan": 1.6},
        ci_evidence=[
            {
                "gate_name": "unit_tests",
                "status": "pass",
                "required": True,
                "critical": False,
                "details": {"passed": "321"},
            },
            {
                "gate_name": "security_scan",
                "status": "pass",
                "required": True,
                "critical": True,
                "details": {"critical_cves": "0"},
            },
        ],
    )
    assert scorecard["release_blocked"] is False

    reloaded = ReleaseReadinessService(store=JsonFileReleaseReadinessStore(str(store_path)))
    listed = reloaded.list_scorecards(tenant_id="tenant-a")
    fetched = reloaded.get_scorecard(scorecard_id="rc-2026-04-19", tenant_id="tenant-a")

    assert len(listed) == 1
    assert fetched is not None
    assert fetched["release_id"] == "v1.8.0-rc1"
