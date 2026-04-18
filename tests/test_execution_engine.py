from project_mimic.engine import ExecutionEngine
from project_mimic.orchestrator.decision_orchestrator import DecisionOrchestrator, OrchestratorConfig
from project_mimic.orchestrator.state_machine import ActionState, StepSignal
from project_mimic.vision.grounding import BBox, DOMNode, UIEntity


def test_execution_engine_returns_click_for_grounded_target() -> None:
    engine = ExecutionEngine(
        orchestrator=DecisionOrchestrator(OrchestratorConfig(min_confidence=0.2, max_retries=1))
    )

    entities = [
        UIEntity(
            entity_id="e1",
            label="Search",
            role="button",
            text="Search Flights",
            bbox=BBox(100, 100, 120, 40),
            confidence=0.9,
        )
    ]
    dom_nodes = [
        DOMNode(
            dom_node_id="search-btn",
            role="button",
            text="Search Flights",
            bbox=BBox(102, 101, 120, 40),
            visible=True,
            enabled=True,
            z_index=5,
        )
    ]

    decision = engine.decide_coordinate_click(entities, dom_nodes)
    assert decision.status == "ok"
    assert decision.state == ActionState.COMPLETE
    assert decision.dom_node_id == "search-btn"


def test_execution_engine_returns_failed_when_state_machine_fails() -> None:
    engine = ExecutionEngine(
        orchestrator=DecisionOrchestrator(OrchestratorConfig(min_confidence=0.2, max_retries=0))
    )

    entities = [
        UIEntity(
            entity_id="e1",
            label="Search",
            role="button",
            text="Search",
            bbox=BBox(100, 100, 80, 30),
            confidence=0.9,
        )
    ]
    dom_nodes = [
        DOMNode(
            dom_node_id="search-btn",
            role="button",
            text="Search",
            bbox=BBox(100, 100, 80, 30),
            visible=True,
            enabled=True,
            z_index=1,
        )
    ]

    decision = engine.decide_coordinate_click(
        entities,
        dom_nodes,
        signals=[StepSignal(frame_ready=True), StepSignal(intent_confident=False), StepSignal()],
    )
    assert decision.status == "execution_failed"
    assert decision.state == ActionState.FAIL


def test_execution_engine_returns_no_target_when_no_interactable_match() -> None:
    engine = ExecutionEngine()

    entities = [
        UIEntity(
            entity_id="e1",
            label="Search",
            role="button",
            text="Search",
            bbox=BBox(100, 100, 80, 30),
            confidence=0.9,
        )
    ]
    dom_nodes = [
        DOMNode(
            dom_node_id="search-btn",
            role="button",
            text="Search",
            bbox=BBox(100, 100, 80, 30),
            visible=False,
            enabled=True,
            z_index=1,
        )
    ]

    decision = engine.decide_coordinate_click(entities, dom_nodes)
    assert decision.status == "no_target"
