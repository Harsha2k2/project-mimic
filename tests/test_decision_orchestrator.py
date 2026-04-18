from project_mimic.orchestrator.decision_orchestrator import (
    ActionCandidate,
    DecisionOrchestrator,
    OrchestratorConfig,
)
from project_mimic.orchestrator.state_machine import ActionState, StepSignal


def test_select_candidate_prefers_weighted_best_score() -> None:
    orchestrator = DecisionOrchestrator(
        OrchestratorConfig(min_confidence=0.6, history_weight=0.25, max_retries=1)
    )

    candidates = [
        ActionCandidate(
            intent="click_search",
            dom_node_id="n1",
            x=10,
            y=10,
            confidence=0.80,
            history_success=0.10,
        ),
        ActionCandidate(
            intent="click_search",
            dom_node_id="n2",
            x=12,
            y=8,
            confidence=0.75,
            history_success=0.95,
        ),
    ]

    selected = orchestrator.select_candidate(candidates)
    assert selected is not None
    assert selected.dom_node_id == "n2"


def test_select_candidate_returns_none_when_confidence_too_low() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(min_confidence=0.9))

    selected = orchestrator.select_candidate(
        [
            ActionCandidate(
                intent="click_search",
                dom_node_id="n1",
                x=10,
                y=10,
                confidence=0.7,
                history_success=0.9,
            )
        ]
    )

    assert selected is None


def test_run_cycle_stops_at_terminal_state() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(max_retries=1))
    final_state = orchestrator.run_cycle(
        [
            StepSignal(frame_ready=True),
            StepSignal(intent_confident=True),
            StepSignal(target_resolved=True),
            StepSignal(motion_planned=True),
            StepSignal(events_ack=True),
            StepSignal(verify_ok=True),
        ]
    )

    assert final_state == ActionState.COMPLETE
