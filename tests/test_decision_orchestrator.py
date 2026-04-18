from project_mimic.orchestrator.decision_orchestrator import (
    ActionCandidate,
    DecisionOrchestrator,
    OrchestratorConfig,
)
from project_mimic.orchestrator.state_machine import ActionState, StepSignal
from project_mimic.orchestrator.strategy import OrchestrationStrategy


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


def test_select_candidate_uses_fallback_when_confidence_too_low() -> None:
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

    assert selected is not None
    assert selected.dom_node_id == "n1"


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


def test_replay_log_records_selection_and_transitions() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(max_retries=1))
    orchestrator.select_candidate(
        [
            ActionCandidate(
                intent="click",
                dom_node_id="n1",
                x=1,
                y=1,
                confidence=0.8,
                history_success=0.2,
            )
        ]
    )
    orchestrator.run_cycle(
        [
            StepSignal(frame_ready=True),
            StepSignal(intent_confident=True),
            StepSignal(target_resolved=True),
            StepSignal(motion_planned=True),
            StepSignal(events_ack=True),
            StepSignal(verify_ok=True),
        ]
    )

    log = orchestrator.get_replay_log()
    assert len(log) > 0
    assert any(event.event_type == "select_candidate" for event in log)
    assert any(event.event_type == "state_transition" for event in log)


class _BoostStrategy(OrchestrationStrategy):
    def calibrate_confidence(self, candidate: ActionCandidate, signal_quality: float) -> float:
        if candidate.dom_node_id == "n1":
            return min(candidate.confidence + 0.2, 1.0)
        return candidate.confidence


def test_site_strategy_can_override_selection_behavior() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(min_confidence=0.6))
    orchestrator.register_strategy("site-a", _BoostStrategy())

    selected = orchestrator.select_candidate(
        [
            ActionCandidate(
                intent="click",
                dom_node_id="n1",
                x=0,
                y=0,
                confidence=0.55,
                history_success=0.2,
            ),
            ActionCandidate(
                intent="click",
                dom_node_id="n2",
                x=0,
                y=0,
                confidence=0.62,
                history_success=0.1,
            ),
        ],
        site_id="site-a",
    )

    assert selected is not None
    assert selected.dom_node_id == "n1"
