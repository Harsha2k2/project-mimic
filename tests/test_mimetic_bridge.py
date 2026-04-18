import json

from project_mimic.mimetic import MimeticEventStream, RustPythonEventBridge


def test_bridge_decodes_rust_pointer_events_into_typed_stream() -> None:
    payload = [
        json.dumps({"t_ms": 0, "x": 1.2, "y": 2.4, "event_type": "move"}),
        json.dumps({"t_ms": 80, "x": 10.0, "y": 20.0, "event_type": "down"}),
        json.dumps({"t_ms": 120, "x": 10.0, "y": 20.0, "event_type": "up"}),
    ]

    stream = RustPythonEventBridge.from_rust_events(
        payload,
        channel="pointer",
        profile="desktop-standard",
        deterministic_seed=7,
    )

    assert isinstance(stream, MimeticEventStream)
    assert stream.channel == "pointer"
    assert stream.profile == "desktop-standard"
    assert stream.deterministic_seed == 7
    assert len(stream.events) == 3


def test_bridge_round_trip_payload_is_stable() -> None:
    payload = [
        json.dumps({"t_ms": 5, "key": "a", "event_type": "keydown"}),
        json.dumps({"t_ms": 35, "key": "a", "event_type": "keyup"}),
    ]

    stream = RustPythonEventBridge.from_rust_events(payload, channel="keyboard", profile="typing-v1")
    restored = RustPythonEventBridge.to_grpc_payload(stream)

    assert [json.loads(item) for item in restored] == [json.loads(item) for item in payload]
