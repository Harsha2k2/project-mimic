import json

from fastapi.testclient import TestClient

from project_mimic.api import create_app
from project_mimic.grpc_runtime import (
    CreateSessionRequest,
    GroundActionRequest,
    SessionServiceHandler,
    VisionServiceHandler,
)


def test_api_and_grpc_session_contract_parity() -> None:
    client = TestClient(create_app())
    api_response = client.post("/api/v1/sessions", json={"goal": "parity", "max_steps": 3})
    assert api_response.status_code == 200

    grpc_service = SessionServiceHandler()
    grpc_response = grpc_service.CreateSession(CreateSessionRequest(goal="parity", max_steps=3))

    assert api_response.json()["observation"]["status"] == "running"
    assert grpc_response.status == "running"


def test_api_decision_and_grpc_grounding_contract_parity() -> None:
    payload = {
        "entities": [
            {
                "entity_id": "e1",
                "label": "Search",
                "role": "button",
                "text": "Search Flights",
                "confidence": 0.9,
                "bbox": {"x": 100, "y": 100, "width": 120, "height": 40},
            }
        ],
        "dom_nodes": [
            {
                "dom_node_id": "search-btn",
                "role": "button",
                "text": "Search Flights",
                "visible": True,
                "enabled": True,
                "z_index": 5,
                "bbox": {"x": 102, "y": 101, "width": 120, "height": 40},
            }
        ],
    }

    client = TestClient(create_app())
    api_response = client.post("/api/v1/decision/click", json=payload)
    assert api_response.status_code == 200

    grpc_service = VisionServiceHandler()
    grpc_response = grpc_service.GroundAction(
        GroundActionRequest(
            intent="search",
            ui_map_json=json.dumps(payload),
        )
    )

    api_body = api_response.json()
    assert api_body["dom_node_id"] == grpc_response.dom_node_id
    assert api_body["x"] == grpc_response.x
    assert api_body["y"] == grpc_response.y
