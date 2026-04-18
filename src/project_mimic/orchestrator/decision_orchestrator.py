"""Decision Orchestrator for selecting grounded actions and running action cycles."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..observability import OpenTelemetryTracer
from .retry_budget import RetryBudgetManager
from .state_machine import ActionState, ActionStateMachine, StepSignal
from .strategy import OrchestrationStrategy, SiteStrategyRegistry


@dataclass(frozen=True)
class ActionCandidate:
    intent: str
    dom_node_id: str
    x: int
    y: int
    confidence: float
    history_success: float = 0.0

    def score(self, history_weight: float = 0.25) -> float:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        if not 0.0 <= self.history_success <= 1.0:
            raise ValueError("history_success must be in [0.0, 1.0]")

        visual_weight = 1.0 - history_weight
        return (visual_weight * self.confidence) + (history_weight * self.history_success)


@dataclass(frozen=True)
class OrchestratorConfig:
    min_confidence: float = 0.60
    history_weight: float = 0.25
    max_retries: int = 2
    default_signal_quality: float = 1.0


@dataclass(frozen=True)
class ReplayEvent:
    timestamp_ms: int
    event_type: str
    payload: dict


class ConfidenceCalibrator:
    def calibrate(self, raw_confidence: float, signal_quality: float, history_success: float) -> float:
        calibrated = (0.70 * raw_confidence) + (0.20 * signal_quality) + (0.10 * history_success)
        return max(0.0, min(calibrated, 1.0))


class DecisionOrchestrator:
    """Selects best grounded action and executes deterministic step lifecycle."""

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        tracer: OpenTelemetryTracer | None = None,
    ) -> None:
        self.config = config or OrchestratorConfig()
        self.state_machine = ActionStateMachine(max_retries=self.config.max_retries)
        self.calibrator = ConfidenceCalibrator()
        self.replay_log: list[ReplayEvent] = []
        self.tracer = tracer or OpenTelemetryTracer(component="orchestrator")
        self.strategy_registry = SiteStrategyRegistry(default_strategy=OrchestrationStrategy())
        self.retry_budget = RetryBudgetManager(
            per_state_caps={
                ActionState.RECOVER: self.config.max_retries,
                ActionState.HYPOTHESIZE: self.config.max_retries + 1,
            }
        )

    def register_strategy(self, site_id: str, strategy: OrchestrationStrategy) -> None:
        self.strategy_registry.register(site_id=site_id, strategy=strategy)

    def select_candidate(
        self,
        candidates: list[ActionCandidate],
        site_id: str | None = None,
        signal_quality: float | None = None,
    ) -> ActionCandidate | None:
        quality = signal_quality if signal_quality is not None else self.config.default_signal_quality
        with self.tracer.start_span(
            "orchestrator.select_candidate",
            attributes={
                "site_id": site_id or "unknown",
                "candidate_count": len(candidates),
                "signal_quality": quality,
            },
        ):
            strategy = self.strategy_registry.resolve(site_id)
            calibrated: list[ActionCandidate] = []

            for candidate in candidates:
                strategy_confidence = strategy.calibrate_confidence(candidate, quality)
                confidence = self.calibrator.calibrate(
                    raw_confidence=strategy_confidence,
                    signal_quality=quality,
                    history_success=candidate.history_success,
                )
                calibrated.append(
                    ActionCandidate(
                        intent=candidate.intent,
                        dom_node_id=candidate.dom_node_id,
                        x=candidate.x,
                        y=candidate.y,
                        confidence=confidence,
                        history_success=candidate.history_success,
                    )
                )

            viable = [c for c in calibrated if c.confidence >= self.config.min_confidence]
            if not viable:
                return self._select_fallback(calibrated, strategy)

            selected = max(
                viable,
                key=lambda c: c.score(history_weight=self.config.history_weight),
            )
            self._record_event(
                "select_candidate",
                {
                    "site_id": site_id,
                    "selected_dom_node_id": selected.dom_node_id,
                    "confidence": selected.confidence,
                },
            )
            return selected

    def run_cycle(self, signals: list[StepSignal]) -> ActionState:
        with self.tracer.start_span(
            "orchestrator.run_cycle",
            attributes={"signal_count": len(signals)},
        ):
            for signal in signals:
                if not self.retry_budget.consume(self.state_machine.state):
                    self._record_event(
                        "retry_budget_exhausted",
                        {"state": self.state_machine.state.value},
                    )
                    self.state_machine.state = ActionState.FAIL
                    return self.state_machine.state

                state = self.state_machine.apply(signal)
                self._record_event(
                    "state_transition",
                    {
                        "state": state.value,
                        "retry_count": self.state_machine.retry_count,
                    },
                )
                if self.state_machine.is_terminal():
                    return state

            return self.state_machine.state

    def reset_cycle(self) -> None:
        self.state_machine.reset()
        self.retry_budget.reset()

    def get_replay_log(self) -> list[ReplayEvent]:
        return list(self.replay_log)

    def _select_fallback(
        self,
        candidates: list[ActionCandidate],
        strategy: OrchestrationStrategy,
    ) -> ActionCandidate | None:
        if not candidates:
            self._record_event("select_candidate", {"result": "none"})
            return None

        selected = max(
            candidates,
            key=lambda c: (
                strategy.fallback_score(c),
                -abs(c.x),
                -abs(c.y),
                c.dom_node_id,
            ),
        )
        self._record_event(
            "select_fallback_candidate",
            {
                "selected_dom_node_id": selected.dom_node_id,
                "confidence": selected.confidence,
            },
        )
        return selected

    def _record_event(self, event_type: str, payload: dict) -> None:
        self.replay_log.append(
            ReplayEvent(
                timestamp_ms=int(time.time() * 1000),
                event_type=event_type,
                payload=payload,
            )
        )
