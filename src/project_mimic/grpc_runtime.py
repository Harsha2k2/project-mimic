"""In-process gRPC-style service handlers aligned with proto contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from .mimetic import MimeticEventStream, RustPythonEventBridge, plan_pointer_stream, synthesize_typing_stream
from .models import ProjectMimicModel
from .orchestrator.decision_orchestrator import ActionCandidate, DecisionOrchestrator
from .session_lifecycle import SessionRegistry
from .vision.grounding import BBox, DOMNode, UIEntity, ground_entities_to_dom


class RequestMeta(ProjectMimicModel):
    trace_id: str = ""
    session_id: str = ""
    idempotency_key: str = ""
    deadline_unix_ms: int = 0


class Ack(ProjectMimicModel):
    ok: bool
    message: str


class CreateSessionRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    goal: str
    max_steps: int = Field(default=20, ge=1)


class CreateSessionResponse(ProjectMimicModel):
    session_id: str
    status: str


class AttachSiteTaskRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    site_id: str
    task: str


class CloseSessionRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)


class CloseSessionResponse(ProjectMimicModel):
    session_id: str
    final_status: str


class AnalyzeFrameRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    screenshot: bytes
    dom_snapshot_json: str = "{}"
    task_hint: str = ""


class AnalyzeFrameResponse(ProjectMimicModel):
    frame_hash: str
    entities_json: list[str]


class GroundActionRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    intent: str
    ui_map_json: str


class GroundActionResponse(ProjectMimicModel):
    dom_node_id: str
    x: int
    y: int
    confidence: float = Field(ge=0.0, le=1.0)


class PlanPointerRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    start_x: int
    start_y: int
    target_x: int
    target_y: int


class PlanPointerResponse(ProjectMimicModel):
    events_json: list[str]
    event_stream: MimeticEventStream


class EmitPointerRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    events_json: list[str] = Field(default_factory=list)


class PlanKeystrokesRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    text: str
    field_type: str = "text"


class PlanKeystrokesResponse(ProjectMimicModel):
    events_json: list[str]
    event_stream: MimeticEventStream


class EmitKeystrokesRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    events_json: list[str] = Field(default_factory=list)


class NextStepRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    blackboard_json: str


class NextStepResponse(ProjectMimicModel):
    action_type: str
    action_payload_json: str


class VerifyStepRequest(ProjectMimicModel):
    meta: RequestMeta = Field(default_factory=RequestMeta)
    expected_outcome_json: str
    observed_outcome_json: str


class VerifyStepResponse(ProjectMimicModel):
    success: bool
    reason: str


class SessionServiceHandler:
    """Implements SessionService RPC handlers using SessionRegistry."""

    def __init__(self, registry: SessionRegistry | None = None) -> None:
        self.registry = registry or SessionRegistry()
        self._site_tasks: dict[str, list[dict[str, str]]] = {}

    def CreateSession(self, request: CreateSessionRequest) -> CreateSessionResponse:
        session_id, _ = self.registry.create(goal=request.goal, max_steps=request.max_steps)
        return CreateSessionResponse(session_id=session_id, status="running")

    def AttachSiteTask(self, request: AttachSiteTaskRequest) -> Ack:
        session_id = request.meta.session_id
        if not session_id:
            return Ack(ok=False, message="meta.session_id is required")

        try:
            self.registry.get(session_id)
        except Exception:
            return Ack(ok=False, message="session not found")

        self._site_tasks.setdefault(session_id, []).append({"site_id": request.site_id, "task": request.task})
        return Ack(ok=True, message="task attached")

    def CloseSession(self, request: CloseSessionRequest) -> CloseSessionResponse:
        session_id = request.meta.session_id
        if not session_id:
            raise ValueError("meta.session_id is required")

        self.registry.mark_completed(session_id)
        record = self.registry.get_record(session_id)
        return CloseSessionResponse(session_id=session_id, final_status=record.status.value)


class VisionServiceHandler:
    """Implements VisionService RPC handlers for frame analysis and grounding."""

    def AnalyzeFrame(self, request: AnalyzeFrameRequest) -> AnalyzeFrameResponse:
        frame_hash = hashlib.sha256(request.screenshot).hexdigest()
        payload = _safe_json_loads(request.dom_snapshot_json)

        entities = payload.get("entities", []) if isinstance(payload, dict) else []
        entities_json = [json.dumps(entity) for entity in entities if isinstance(entity, dict)]
        return AnalyzeFrameResponse(frame_hash=frame_hash, entities_json=entities_json)

    def GroundAction(self, request: GroundActionRequest) -> GroundActionResponse:
        payload = _safe_json_loads(request.ui_map_json)
        if not isinstance(payload, dict):
            raise ValueError("ui_map_json must be a json object")

        entities = _to_entities(payload.get("entities", []))
        dom_nodes = _to_dom_nodes(payload.get("dom_nodes", []))

        if entities and dom_nodes:
            grounded = ground_entities_to_dom(entities, dom_nodes, top_k=1)
            preferred = _pick_entity_for_intent(entities, request.intent)
            matches = grounded.get(preferred.entity_id, []) if preferred else []
            if matches:
                top = matches[0]
                return GroundActionResponse(
                    dom_node_id=top.dom_node_id,
                    x=top.x,
                    y=top.y,
                    confidence=min(max(top.score, 0.0), 1.0),
                )

        return GroundActionResponse(dom_node_id="", x=0, y=0, confidence=0.0)


class MimeticServiceHandler:
    """Implements MimeticService RPC handlers backed by deterministic planners."""

    def __init__(self, viewport_width: int = 1280, viewport_height: int = 720) -> None:
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def PlanPointer(self, request: PlanPointerRequest) -> PlanPointerResponse:
        seed = _seed_from_meta(request.meta)
        stream = plan_pointer_stream(
            start_x=float(request.start_x),
            start_y=float(request.start_y),
            target_x=float(request.target_x),
            target_y=float(request.target_y),
            viewport_width=self.viewport_width,
            viewport_height=self.viewport_height,
            deterministic_seed=seed,
        )
        return PlanPointerResponse(events_json=RustPythonEventBridge.to_grpc_payload(stream), event_stream=stream)

    def EmitPointer(self, request: EmitPointerRequest) -> Ack:
        return Ack(ok=True, message=f"pointer events accepted: {len(request.events_json)}")

    def PlanKeystrokes(self, request: PlanKeystrokesRequest) -> PlanKeystrokesResponse:
        seed = _seed_from_meta(request.meta)
        base_delay = 75 if request.field_type in {"email", "password"} else 60
        stream = synthesize_typing_stream(
            request.text,
            base_delay_ms=base_delay,
            deterministic_seed=seed,
        )
        return PlanKeystrokesResponse(events_json=RustPythonEventBridge.to_grpc_payload(stream), event_stream=stream)

    def EmitKeystrokes(self, request: EmitKeystrokesRequest) -> Ack:
        return Ack(ok=True, message=f"keystroke events accepted: {len(request.events_json)}")


class OrchestratorServiceHandler:
    """Implements OrchestratorService RPC handlers using decision heuristics."""

    def __init__(self, orchestrator: DecisionOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or DecisionOrchestrator()

    def NextStep(self, request: NextStepRequest) -> NextStepResponse:
        payload = _safe_json_loads(request.blackboard_json)
        if not isinstance(payload, dict):
            return NextStepResponse(action_type="wait", action_payload_json=json.dumps({"wait_ms": 200}))

        if "next_action" in payload and isinstance(payload["next_action"], dict):
            next_action = payload["next_action"]
            action_type = str(next_action.get("action_type", "wait"))
            return NextStepResponse(action_type=action_type, action_payload_json=json.dumps(next_action))

        candidates_payload = payload.get("candidates", [])
        candidates: list[ActionCandidate] = []
        for item in candidates_payload:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(
                    ActionCandidate(
                        intent=str(item.get("intent", "click")),
                        dom_node_id=str(item.get("dom_node_id", "")),
                        x=int(item.get("x", 0)),
                        y=int(item.get("y", 0)),
                        confidence=float(item.get("confidence", 0.0)),
                        history_success=float(item.get("history_success", 0.0)),
                    )
                )
            except (TypeError, ValueError):
                continue

        selected = self.orchestrator.select_candidate(candidates)
        if selected is None:
            return NextStepResponse(action_type="wait", action_payload_json=json.dumps({"wait_ms": 200}))

        payload_out = {
            "action_type": "click",
            "target": selected.dom_node_id,
            "x": selected.x,
            "y": selected.y,
            "score": selected.score(self.orchestrator.config.history_weight),
        }
        return NextStepResponse(action_type="click", action_payload_json=json.dumps(payload_out))

    def VerifyStep(self, request: VerifyStepRequest) -> VerifyStepResponse:
        expected = _safe_json_loads(request.expected_outcome_json)
        observed = _safe_json_loads(request.observed_outcome_json)
        if expected == observed:
            return VerifyStepResponse(success=True, reason="expected outcome matched observed outcome")

        return VerifyStepResponse(success=False, reason="expected outcome mismatch")


@dataclass(frozen=True)
class GrpcRuntimeBundle:
    session: SessionServiceHandler
    vision: VisionServiceHandler
    mimetic: MimeticServiceHandler
    orchestrator: OrchestratorServiceHandler


def build_default_grpc_runtime() -> GrpcRuntimeBundle:
    registry = SessionRegistry()
    return GrpcRuntimeBundle(
        session=SessionServiceHandler(registry=registry),
        vision=VisionServiceHandler(),
        mimetic=MimeticServiceHandler(),
        orchestrator=OrchestratorServiceHandler(),
    )


def _safe_json_loads(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def _seed_from_meta(meta: RequestMeta) -> int | None:
    key = meta.idempotency_key.strip()
    if not key:
        return None
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _pick_entity_for_intent(entities: list[UIEntity], intent: str) -> UIEntity | None:
    lowered = intent.strip().lower()
    if lowered:
        for entity in entities:
            if lowered in entity.label.lower() or lowered in entity.text.lower():
                return entity
    return entities[0] if entities else None


def _to_entities(raw_entities: list[dict[str, Any]]) -> list[UIEntity]:
    entities: list[UIEntity] = []
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        bbox_raw = item.get("bbox", {})
        if not isinstance(bbox_raw, dict):
            continue
        try:
            entities.append(
                UIEntity(
                    entity_id=str(item.get("entity_id", "")),
                    label=str(item.get("label", "")),
                    role=str(item.get("role", "unknown")),
                    text=str(item.get("text", "")),
                    confidence=float(item.get("confidence", 0.0)),
                    bbox=BBox(
                        x=int(bbox_raw.get("x", 0)),
                        y=int(bbox_raw.get("y", 0)),
                        width=int(bbox_raw.get("width", 1)),
                        height=int(bbox_raw.get("height", 1)),
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return entities


def _to_dom_nodes(raw_nodes: list[dict[str, Any]]) -> list[DOMNode]:
    dom_nodes: list[DOMNode] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        bbox_raw = item.get("bbox", {})
        if not isinstance(bbox_raw, dict):
            continue
        try:
            dom_nodes.append(
                DOMNode(
                    dom_node_id=str(item.get("dom_node_id", "")),
                    role=str(item.get("role", "unknown")),
                    text=str(item.get("text", "")),
                    visible=bool(item.get("visible", True)),
                    enabled=bool(item.get("enabled", True)),
                    z_index=int(item.get("z_index", 0)),
                    bbox=BBox(
                        x=int(bbox_raw.get("x", 0)),
                        y=int(bbox_raw.get("y", 0)),
                        width=int(bbox_raw.get("width", 1)),
                        height=int(bbox_raw.get("height", 1)),
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    return dom_nodes
