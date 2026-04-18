"""Decision Orchestrator for selecting grounded actions and running action cycles."""

from __future__ import annotations

from dataclasses import dataclass

from .state_machine import ActionState, ActionStateMachine, StepSignal


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


class DecisionOrchestrator:
    """Selects best grounded action and executes deterministic step lifecycle."""

    def __init__(self, config: OrchestratorConfig | None = None) -> None:
        self.config = config or OrchestratorConfig()
        self.state_machine = ActionStateMachine(max_retries=self.config.max_retries)

    def select_candidate(self, candidates: list[ActionCandidate]) -> ActionCandidate | None:
        viable = [c for c in candidates if c.confidence >= self.config.min_confidence]
        if not viable:
            return None

        return max(
            viable,
            key=lambda c: c.score(history_weight=self.config.history_weight),
        )

    def run_cycle(self, signals: list[StepSignal]) -> ActionState:
        for signal in signals:
            state = self.state_machine.apply(signal)
            if self.state_machine.is_terminal():
                return state

        return self.state_machine.state

    def reset_cycle(self) -> None:
        self.state_machine.reset()
