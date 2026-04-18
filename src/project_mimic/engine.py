"""Execution engine integrating vision grounding and orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .orchestrator.decision_orchestrator import ActionCandidate, DecisionOrchestrator
from .orchestrator.state_machine import ActionState, StepSignal
from .vision.grounding import DOMNode, UIEntity, ground_entities_to_dom


@dataclass(frozen=True)
class ClickDecision:
    status: str
    state: ActionState
    dom_node_id: str | None = None
    x: int | None = None
    y: int | None = None
    score: float | None = None


class ExecutionEngine:
    """Maps visual entities to executable coordinate-click decisions."""

    def __init__(self, orchestrator: DecisionOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or DecisionOrchestrator()

    def decide_coordinate_click(
        self,
        entities: list[UIEntity],
        dom_nodes: list[DOMNode],
        signals: list[StepSignal] | None = None,
    ) -> ClickDecision:
        grounded = ground_entities_to_dom(entities, dom_nodes, top_k=1)

        candidates: list[ActionCandidate] = []
        for entity in entities:
            top_candidates = grounded.get(entity.entity_id, [])
            if not top_candidates:
                continue

            top = top_candidates[0]
            candidates.append(
                ActionCandidate(
                    intent=entity.label or entity.role,
                    dom_node_id=top.dom_node_id,
                    x=top.x,
                    y=top.y,
                    confidence=min(max(top.score, 0.0), 1.0),
                    history_success=0.0,
                )
            )

        selected = self.orchestrator.select_candidate(candidates)
        if selected is None:
            return ClickDecision(status="no_target", state=self.orchestrator.state_machine.state)

        cycle_signals = signals or [
            StepSignal(frame_ready=True),
            StepSignal(intent_confident=True),
            StepSignal(target_resolved=True),
            StepSignal(motion_planned=True),
            StepSignal(events_ack=True),
            StepSignal(verify_ok=True),
        ]
        final_state = self.orchestrator.run_cycle(cycle_signals)
        if final_state != ActionState.COMPLETE:
            return ClickDecision(
                status="execution_failed",
                state=final_state,
                dom_node_id=selected.dom_node_id,
                x=selected.x,
                y=selected.y,
                score=selected.score(self.orchestrator.config.history_weight),
            )

        return ClickDecision(
            status="ok",
            state=final_state,
            dom_node_id=selected.dom_node_id,
            x=selected.x,
            y=selected.y,
            score=selected.score(self.orchestrator.config.history_weight),
        )
