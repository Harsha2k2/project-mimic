from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_session_proto_contains_service_and_rpcs() -> None:
    text = _read("proto/session/v1/session.proto")
    assert "service SessionService" in text
    assert "rpc CreateSession" in text
    assert "rpc AttachSiteTask" in text
    assert "rpc CloseSession" in text


def test_vision_proto_contains_service_and_rpcs() -> None:
    text = _read("proto/vision/v1/vision.proto")
    assert "service VisionService" in text
    assert "rpc AnalyzeFrame" in text
    assert "rpc GroundAction" in text


def test_mimetic_proto_contains_service_and_rpcs() -> None:
    text = _read("proto/mimetic/v1/mimetic.proto")
    assert "service MimeticService" in text
    assert "rpc PlanPointer" in text
    assert "rpc EmitPointer" in text
    assert "rpc PlanKeystrokes" in text
    assert "rpc EmitKeystrokes" in text


def test_orchestrator_proto_contains_service_and_rpcs() -> None:
    text = _read("proto/orchestrator/v1/orchestrator.proto")
    assert "service OrchestratorService" in text
    assert "rpc NextStep" in text
    assert "rpc VerifyStep" in text
