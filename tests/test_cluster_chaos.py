import pytest

from project_mimic.cluster_chaos import ChaosScenario, ClusterChaosTestSuite, REQUIRED_FAULT_CLASSES


def test_cluster_chaos_plan_covers_required_fault_classes() -> None:
    suite = ClusterChaosTestSuite()

    plan = suite.plan()
    fault_classes = {scenario["fault_class"] for scenario in plan}

    for required_fault in REQUIRED_FAULT_CLASSES:
        assert required_fault in fault_classes
    assert all(int(scenario["duration_seconds"]) > 0 for scenario in plan)


def test_cluster_chaos_run_returns_healthy_report() -> None:
    suite = ClusterChaosTestSuite()

    report = suite.run()

    assert report["run_id"].startswith("chaos_")
    assert float(report["finished_at"]) >= float(report["started_at"])
    assert report["overall_healthy"] is True
    assert int(report["scenario_count"]) == len(report["results"])

    for scenario in report["results"]:
        assert scenario["healthy"] is True
        assert set(scenario["expected_signals"]).issubset(set(scenario["observed_signals"]))


def test_cluster_chaos_suite_rejects_missing_required_fault_class() -> None:
    suite = ClusterChaosTestSuite(
        scenarios=[
            ChaosScenario(
                scenario_id="node-only",
                fault_class="node_loss",
                target="deployment/mimic-control-plane",
                duration_seconds=30,
                expected_signals=("pod_rescheduled",),
            ),
            ChaosScenario(
                scenario_id="network-only",
                fault_class="network_partition",
                target="mimic-browser-worker<->mimic-triton",
                duration_seconds=30,
                expected_signals=("request_timeout_observed",),
            ),
        ]
    )

    with pytest.raises(ValueError, match="missing required chaos fault classes: storage_fault"):
        suite.plan()


def test_cluster_chaos_suite_rejects_unsupported_fault_class() -> None:
    suite = ClusterChaosTestSuite(
        scenarios=[
            ChaosScenario(
                scenario_id="node-loss",
                fault_class="node_loss",
                target="deployment/mimic-control-plane",
                duration_seconds=30,
                expected_signals=("pod_rescheduled",),
            ),
            ChaosScenario(
                scenario_id="network-partition",
                fault_class="network_partition",
                target="mimic-browser-worker<->mimic-triton",
                duration_seconds=30,
                expected_signals=("request_timeout_observed",),
            ),
            ChaosScenario(
                scenario_id="storage-fault",
                fault_class="storage_fault",
                target="artifact-writer",
                duration_seconds=30,
                expected_signals=("write_error_detected",),
            ),
            ChaosScenario(
                scenario_id="unsupported",
                fault_class="dns_poisoning",
                target="cluster-dns",
                duration_seconds=30,
                expected_signals=("resolver_failure",),
            ),
        ]
    )

    with pytest.raises(ValueError, match="unsupported chaos fault classes: dns_poisoning"):
        suite.run()
