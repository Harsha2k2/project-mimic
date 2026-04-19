from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.privacy_analytics import (
    JsonFilePrivacyAnalyticsStore,
    PrivacyPreservingAnalyticsService,
)


def test_privacy_analytics_policy_ingest_and_report_flow(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    policy = client.post(
        "/api/v1/analytics/privacy/policies/tenant-a",
        headers={"X-API-Key": "admin-key"},
        json={
            "epsilon": 0.7,
            "min_group_size": 2,
            "max_groups": 50,
            "redact_dimension_keys": ["country"],
            "noise_seed": "tenant-a-seed",
        },
    )
    assert policy.status_code == 200
    assert policy.json()["tenant_id"] == "tenant-a"

    for payload in [
        {
            "metric_name": "page_view",
            "value": 10.0,
            "dimensions": {"country": "us", "channel": "email"},
        },
        {
            "metric_name": "page_view",
            "value": 12.0,
            "dimensions": {"country": "us", "channel": "email"},
        },
        {
            "metric_name": "page_view",
            "value": 4.0,
            "dimensions": {"country": "ca", "channel": "ad"},
        },
    ]:
        ingested = client.post(
            "/api/v1/analytics/privacy/events",
            headers={"X-API-Key": "operator-key"},
            json=payload,
        )
        assert ingested.status_code == 200

    report = client.post(
        "/api/v1/analytics/privacy/reports/generate",
        headers={"X-API-Key": "operator-key"},
        json={
            "metric_name": "page_view",
            "group_by": ["country"],
        },
    )
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["tenant_id"] == "tenant-a"
    assert report_payload["total_events"] == 3
    assert report_payload["visible_groups"] == 1
    assert report_payload["suppressed_groups"] == 1
    assert report_payload["groups"][0]["group"]["country"] == "[redacted]"

    list_reports = client.get(
        "/api/v1/analytics/privacy/reports",
        headers={"X-API-Key": "operator-key"},
    )
    assert list_reports.status_code == 200
    assert list_reports.json()["total"] >= 1

    report_id = report_payload["report_id"]
    fetched = client.get(
        f"/api/v1/analytics/privacy/reports/{report_id}",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["report_id"] == report_id


def test_privacy_analytics_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a,admin-key:tenant-a")

    client = TestClient(create_app())

    forbidden_policy = client.post(
        "/api/v1/analytics/privacy/policies/tenant-a",
        headers={"X-API-Key": "operator-key"},
        json={
            "epsilon": 1.0,
            "min_group_size": 2,
            "max_groups": 10,
            "redact_dimension_keys": [],
            "noise_seed": "seed",
        },
    )
    assert forbidden_policy.status_code == 403

    seeded_policy = client.post(
        "/api/v1/analytics/privacy/policies/tenant-a",
        headers={"X-API-Key": "admin-key"},
        json={
            "epsilon": 1.0,
            "min_group_size": 1,
            "max_groups": 10,
            "redact_dimension_keys": [],
            "noise_seed": "seed",
        },
    )
    assert seeded_policy.status_code == 200

    legacy_event = client.post(
        "/analytics/privacy/events",
        headers={"X-API-Key": "operator-key"},
        json={
            "metric_name": "queue_depth",
            "value": 5.0,
            "dimensions": {"region": "us-west"},
        },
    )
    assert legacy_event.status_code == 200
    assert legacy_event.headers.get("Deprecation") == "true"

    forbidden_generate = client.post(
        "/api/v1/analytics/privacy/reports/generate",
        headers={"X-API-Key": "viewer-key"},
        json={"metric_name": "queue_depth", "group_by": ["region"]},
    )
    assert forbidden_generate.status_code == 403

    legacy_generate = client.post(
        "/analytics/privacy/reports/generate",
        headers={"X-API-Key": "operator-key"},
        json={"metric_name": "queue_depth", "group_by": ["region"]},
    )
    assert legacy_generate.status_code == 200
    assert legacy_generate.headers.get("Deprecation") == "true"


def test_json_file_privacy_analytics_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "privacy-analytics.json"
    service = PrivacyPreservingAnalyticsService(store=JsonFilePrivacyAnalyticsStore(str(store_path)))

    service.upsert_policy(
        tenant_id="tenant-a",
        epsilon=0.9,
        min_group_size=1,
        max_groups=20,
        redact_dimension_keys=["country"],
        noise_seed="seed-a",
    )
    service.ingest_event(
        tenant_id="tenant-a",
        metric_name="requests",
        value=4.0,
        dimensions={"country": "us", "region": "us-east"},
    )

    report = service.generate_report(
        tenant_id="tenant-a",
        metric_name="requests",
        group_by=["country", "region"],
    )
    assert report["visible_groups"] == 1

    reloaded = PrivacyPreservingAnalyticsService(store=JsonFilePrivacyAnalyticsStore(str(store_path)))
    policy = reloaded.get_policy(tenant_id="tenant-a")
    reports = reloaded.list_reports(tenant_id="tenant-a", limit=10)

    assert policy is not None
    assert policy["tenant_id"] == "tenant-a"
    assert len(reports) >= 1
