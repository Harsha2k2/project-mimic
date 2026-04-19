from pathlib import Path

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.benchmark_lab import BenchmarkLabService, JsonFileBenchmarkLabStore


def test_benchmark_lab_cross_version_comparison_reproducibility(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "admin-key,operator-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "admin-key:admin,operator-key:operator")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "admin-key:tenant-a,operator-key:tenant-a")

    client = TestClient(create_app())

    suite = client.post(
        "/api/v1/benchmarks/lab/suites/core-regression",
        headers={"X-API-Key": "admin-key"},
        json={
            "name": "Core Regression Suite",
            "description": "Compare baseline and candidate runtime quality",
            "task_ids": ["checkout", "search", "login"],
            "score_regression_threshold": 0.02,
            "latency_regression_threshold_ms": 35.0,
            "sample_count": 3,
            "deterministic_seed": 99,
            "active": True,
        },
    )
    assert suite.status_code == 200

    run_one = client.post(
        "/api/v1/benchmarks/lab/runs/run-a",
        headers={"X-API-Key": "operator-key"},
        json={
            "suite_id": "core-regression",
            "baseline_version": "1.3.0",
            "candidate_version": "1.4.0",
            "initiated_by": "ci-regression-job",
        },
    )
    assert run_one.status_code == 200

    run_two = client.post(
        "/api/v1/benchmarks/lab/runs/run-b",
        headers={"X-API-Key": "operator-key"},
        json={
            "suite_id": "core-regression",
            "baseline_version": "1.3.0",
            "candidate_version": "1.4.0",
            "initiated_by": "ci-regression-job",
        },
    )
    assert run_two.status_code == 200

    run_one_payload = run_one.json()
    run_two_payload = run_two.json()
    assert run_one_payload["suite_id"] == "core-regression"
    assert run_one_payload["status"] in {"pass", "regression_detected"}
    assert run_one_payload["reproducibility_fingerprint"] == run_two_payload["reproducibility_fingerprint"]
    assert run_one_payload["task_comparisons"] == run_two_payload["task_comparisons"]

    listed_runs = client.get(
        "/api/v1/benchmarks/lab/runs",
        headers={"X-API-Key": "operator-key"},
        params={"suite_id": "core-regression"},
    )
    assert listed_runs.status_code == 200
    assert listed_runs.json()["total"] >= 2

    fetched_run = client.get(
        "/api/v1/benchmarks/lab/runs/run-a",
        headers={"X-API-Key": "operator-key"},
    )
    assert fetched_run.status_code == 200
    assert fetched_run.json()["run_id"] == "run-a"


def test_benchmark_lab_rbac_and_legacy_headers(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_KEYS", "viewer-key,operator-key,admin-key")
    monkeypatch.setenv("API_AUTH_ROLE_MAP", "viewer-key:viewer,operator-key:operator,admin-key:admin")
    monkeypatch.setenv("API_AUTH_TENANT_MAP", "viewer-key:tenant-a,operator-key:tenant-a,admin-key:tenant-a")

    client = TestClient(create_app())

    forbidden_suite = client.post(
        "/api/v1/benchmarks/lab/suites/core-regression",
        headers={"X-API-Key": "operator-key"},
        json={
            "name": "Core Regression Suite",
            "description": "Compare baseline and candidate runtime quality",
            "task_ids": ["checkout"],
            "score_regression_threshold": 0.02,
            "latency_regression_threshold_ms": 35.0,
            "sample_count": 3,
            "deterministic_seed": 99,
            "active": True,
        },
    )
    assert forbidden_suite.status_code == 403

    suite = client.post(
        "/api/v1/benchmarks/lab/suites/core-regression",
        headers={"X-API-Key": "admin-key"},
        json={
            "name": "Core Regression Suite",
            "description": "Compare baseline and candidate runtime quality",
            "task_ids": ["checkout"],
            "score_regression_threshold": 0.02,
            "latency_regression_threshold_ms": 35.0,
            "sample_count": 3,
            "deterministic_seed": 99,
            "active": True,
        },
    )
    assert suite.status_code == 200

    forbidden_run = client.post(
        "/api/v1/benchmarks/lab/runs/run-a",
        headers={"X-API-Key": "viewer-key"},
        json={
            "suite_id": "core-regression",
            "baseline_version": "1.3.0",
            "candidate_version": "1.4.0",
            "initiated_by": "viewer",
        },
    )
    assert forbidden_run.status_code == 403

    legacy_run = client.post(
        "/benchmarks/lab/runs/run-a",
        headers={"X-API-Key": "operator-key"},
        json={
            "suite_id": "core-regression",
            "baseline_version": "1.3.0",
            "candidate_version": "1.4.0",
            "initiated_by": "operator",
        },
    )
    assert legacy_run.status_code == 200
    assert legacy_run.headers.get("Deprecation") == "true"

    legacy_suite = client.get(
        "/benchmarks/lab/suites/core-regression",
        headers={"X-API-Key": "operator-key"},
    )
    assert legacy_suite.status_code == 200
    assert legacy_suite.headers.get("Deprecation") == "true"


def test_json_file_benchmark_lab_store_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "benchmark-lab.json"
    service = BenchmarkLabService(store=JsonFileBenchmarkLabStore(str(store_path)))

    service.upsert_suite(
        suite_id="core-regression",
        name="Core Regression Suite",
        description="Compare baseline and candidate runtime quality",
        task_ids=["checkout", "search", "login"],
        score_regression_threshold=0.02,
        latency_regression_threshold_ms=35.0,
        sample_count=3,
        deterministic_seed=99,
        active=True,
    )

    run = service.run_comparison(
        tenant_id="tenant-a",
        run_id="run-a",
        suite_id="core-regression",
        baseline_version="1.3.0",
        candidate_version="1.4.0",
        initiated_by="ci-regression-job",
    )
    assert run["reproducibility_fingerprint"]

    reloaded = BenchmarkLabService(store=JsonFileBenchmarkLabStore(str(store_path)))
    suites = reloaded.list_suites()
    runs = reloaded.list_runs(tenant_id="tenant-a")

    assert len(suites) == 1
    assert len(runs) == 1
