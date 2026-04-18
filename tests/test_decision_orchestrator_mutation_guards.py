from project_mimic.orchestrator.decision_orchestrator import (
    ActionCandidate,
    DecisionOrchestrator,
    OrchestratorConfig,
)


def test_mutation_guard_confidence_threshold_filtering() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(min_confidence=0.7, history_weight=0.25))

    selected = orchestrator.select_candidate(
        [
            ActionCandidate(
                intent="high-history",
                dom_node_id="node-history",
                x=10,
                y=10,
                confidence=0.45,
                history_success=1.0,
            ),
            ActionCandidate(
                intent="threshold-pass",
                dom_node_id="node-pass",
                x=20,
                y=20,
                confidence=0.75,
                history_success=0.0,
            ),
        ]
    )

    assert selected is not None
    assert selected.dom_node_id == "node-pass"


def test_mutation_guard_history_weight_influences_selection() -> None:
    orchestrator = DecisionOrchestrator(OrchestratorConfig(min_confidence=0.5, history_weight=0.6))

    selected = orchestrator.select_candidate(
        [
            ActionCandidate(
                intent="visual",
                dom_node_id="node-visual",
                x=1,
                y=1,
                confidence=0.9,
                history_success=0.0,
            ),
            ActionCandidate(
                intent="reliable",
                dom_node_id="node-history",
                x=2,
                y=2,
                confidence=0.7,
                history_success=1.0,
            ),
        ]
    )

    assert selected is not None
    assert selected.dom_node_id == "node-history"
