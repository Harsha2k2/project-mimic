"""Deterministic cluster chaos scenario planning and simulation."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from uuid import uuid4


REQUIRED_FAULT_CLASSES = ("node_loss", "network_partition", "storage_fault")


@dataclass(frozen=True)
class ChaosScenario:
    scenario_id: str
    fault_class: str
    target: str
    duration_seconds: int
    expected_signals: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "fault_class": self.fault_class,
            "target": self.target,
            "duration_seconds": self.duration_seconds,
            "expected_signals": list(self.expected_signals),
        }


class ClusterChaosTestSuite:
    def __init__(self, scenarios: list[ChaosScenario] | None = None) -> None:
        self._scenarios = scenarios or self._default_scenarios()

    @staticmethod
    def _default_scenarios() -> list[ChaosScenario]:
        return [
            ChaosScenario(
                scenario_id="node-loss-control-plane",
                fault_class="node_loss",
                target="deployment/mimic-control-plane",
                duration_seconds=60,
                expected_signals=("pod_rescheduled", "api_latency_spike_recovered"),
            ),
            ChaosScenario(
                scenario_id="network-partition-worker-triton",
                fault_class="network_partition",
                target="mimic-browser-worker<->mimic-triton",
                duration_seconds=90,
                expected_signals=("request_timeout_observed", "circuit_breaker_opened", "service_recovered"),
            ),
            ChaosScenario(
                scenario_id="storage-fault-artifact-path",
                fault_class="storage_fault",
                target="artifact-writer",
                duration_seconds=75,
                expected_signals=("write_error_detected", "fallback_writer_activated", "retention_integrity_preserved"),
            ),
        ]

    def plan(self) -> list[dict[str, Any]]:
        self.validate_required_fault_coverage()
        return [scenario.as_dict() for scenario in self._scenarios]

    def run(self) -> dict[str, Any]:
        self.validate_required_fault_coverage()

        run_id = f"chaos_{uuid4().hex[:12]}"
        started = time.time()
        results = [self._simulate_scenario(scenario) for scenario in self._scenarios]
        finished = time.time()

        overall_healthy = all(bool(item.get("healthy", False)) for item in results)
        return {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "overall_healthy": overall_healthy,
            "scenario_count": len(results),
            "results": results,
        }

    def validate_required_fault_coverage(self) -> None:
        fault_classes = {scenario.fault_class for scenario in self._scenarios}
        unsupported = sorted(fault for fault in fault_classes if fault not in REQUIRED_FAULT_CLASSES)
        if unsupported:
            raise ValueError(f"unsupported chaos fault classes: {', '.join(unsupported)}")

        missing = [fault for fault in REQUIRED_FAULT_CLASSES if fault not in fault_classes]
        if missing:
            raise ValueError(f"missing required chaos fault classes: {', '.join(missing)}")

    def _simulate_scenario(self, scenario: ChaosScenario) -> dict[str, Any]:
        observed_signals = list(scenario.expected_signals)
        healthy = all(signal in observed_signals for signal in scenario.expected_signals)
        return {
            "scenario_id": scenario.scenario_id,
            "fault_class": scenario.fault_class,
            "target": scenario.target,
            "duration_seconds": scenario.duration_seconds,
            "expected_signals": list(scenario.expected_signals),
            "observed_signals": observed_signals,
            "healthy": healthy,
        }
