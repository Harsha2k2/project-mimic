import json

from project_mimic.grpc_runtime import (
    Ack,
    AnalyzeFrameRequest,
    AttachSiteTaskRequest,
    CloseSessionRequest,
    CreateSessionRequest,
    EmitKeystrokesRequest,
    EmitPointerRequest,
    GroundActionRequest,
    MimeticServiceHandler,
    NextStepRequest,
    OrchestratorServiceHandler,
    PlanKeystrokesRequest,
    PlanPointerRequest,
    RequestMeta,
    SessionServiceHandler,
    VerifyStepRequest,
    VisionServiceHandler,
)


def test_session_service_handlers_match_proto_shapes() -> None:
    service = SessionServiceHandler()
    create = service.CreateSession(CreateSessionRequest(goal="book flight", max_steps=5))

    assert create.status == "running"
    assert create.session_id

    attach_ack = service.AttachSiteTask(
        AttachSiteTaskRequest(
            meta=RequestMeta(session_id=create.session_id),
            site_id="site-a",
            task="search",
        )
    )
    assert isinstance(attach_ack, Ack)
    assert attach_ack.ok is True

    close = service.CloseSession(CloseSessionRequest(meta=RequestMeta(session_id=create.session_id)))
    assert close.session_id == create.session_id
    assert close.final_status == "completed"


def test_vision_service_handlers_match_proto_shapes() -> None:
    service = VisionServiceHandler()
    analyze = service.AnalyzeFrame(
        AnalyzeFrameRequest(
            screenshot=b"frame-bytes",
            dom_snapshot_json=json.dumps(
                {
                    "entities": [
                        {
                            "entity_id": "e1",
                            "label": "Search",
                            "role": "button",
                            "text": "Search",
                            "confidence": 0.9,
                            "bbox": {"x": 10, "y": 20, "width": 80, "height": 30},
                        }
                    ]
                }
            ),
            task_hint="find search",
        )
    )
    assert len(analyze.frame_hash) == 64
    assert len(analyze.entities_json) == 1

    grounded = service.GroundAction(
        GroundActionRequest(
            intent="search",
            ui_map_json=json.dumps(
                {
                    "entities": [
                        {
                            "entity_id": "e1",
                            "label": "Search",
                            "role": "button",
                            "text": "Search",
                            "confidence": 0.9,
                            "bbox": {"x": 10, "y": 20, "width": 80, "height": 30},
                        }
                    ],
                    "dom_nodes": [
                        {
                            "dom_node_id": "search-btn",
                            "role": "button",
                            "text": "Search",
                            "visible": True,
                            "enabled": True,
                            "z_index": 1,
                            "bbox": {"x": 12, "y": 22, "width": 80, "height": 30},
                        }
                    ],
                }
            ),
        )
    )
    assert grounded.dom_node_id == "search-btn"
    assert grounded.confidence > 0.0


def test_mimetic_service_handlers_match_proto_shapes() -> None:
    service = MimeticServiceHandler()
    pointer = service.PlanPointer(
        PlanPointerRequest(
            meta=RequestMeta(idempotency_key="seeded"),
            start_x=10,
            start_y=20,
            target_x=120,
            target_y=80,
        )
    )
    assert pointer.events_json
    assert pointer.event_stream.channel == "pointer"

    pointer_ack = service.EmitPointer(EmitPointerRequest(events_json=pointer.events_json))
    assert pointer_ack.ok is True

    keys = service.PlanKeystrokes(
        PlanKeystrokesRequest(
            meta=RequestMeta(idempotency_key="seeded"),
            text="hello",
            field_type="text",
        )
    )
    assert keys.events_json
    assert keys.event_stream.channel == "keyboard"

    key_ack = service.EmitKeystrokes(EmitKeystrokesRequest(events_json=keys.events_json))
    assert key_ack.ok is True


def test_orchestrator_service_handlers_match_proto_shapes() -> None:
    service = OrchestratorServiceHandler()

    next_step = service.NextStep(
        NextStepRequest(
            blackboard_json=json.dumps(
                {
                    "candidates": [
                        {
                            "intent": "search",
                            "dom_node_id": "search-btn",
                            "x": 100,
                            "y": 110,
                            "confidence": 0.9,
                            "history_success": 0.2,
                        }
                    ]
                }
            )
        )
    )
    assert next_step.action_type == "click"
    payload = json.loads(next_step.action_payload_json)
    assert payload["target"] == "search-btn"

    verify_ok = service.VerifyStep(
        VerifyStepRequest(
            expected_outcome_json=json.dumps({"status": "ok"}),
            observed_outcome_json=json.dumps({"status": "ok"}),
        )
    )
    assert verify_ok.success is True
    assert "matched" in verify_ok.reason
