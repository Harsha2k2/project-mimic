"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

from enum import Enum
import os
from threading import Event, Thread
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field

from .error_mapping import map_exception_to_error
from .engine import ExecutionEngine
from .models import Observation, ProjectMimicModel, Reward, UIAction
from .observability import InMemoryMetrics, OpenTelemetryTracer
from .security import redact_sensitive_structure, redact_sensitive_text
from .orchestrator.decision_orchestrator import DecisionOrchestrator
from .session_lifecycle import (
    InvalidSessionTransitionError,
    SessionExpiredError,
    SessionRegistry,
    SessionStatus,
)
from .vision.grounding import BBox, DOMNode, UIEntity


class APIPayloadModel(ProjectMimicModel):
    schema_version: str = "1.0"


class CreateSessionRequest(APIPayloadModel):
    goal: str
    max_steps: int = Field(default=20, ge=1)


class ResetSessionRequest(APIPayloadModel):
    goal: str | None = None


class SessionCreatedResponse(APIPayloadModel):
    session_id: str
    observation: Observation


class StepResponse(APIPayloadModel):
    observation: Observation
    reward: Reward
    done: bool
    info: dict[str, Any]


class SessionListResponse(APIPayloadModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    sort_by: str
    sort_order: str
    filters: dict[str, Any]


class BBoxPayload(APIPayloadModel):
    x: int
    y: int
    width: int
    height: int


class UIEntityPayload(APIPayloadModel):
    entity_id: str
    label: str
    role: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBoxPayload


class DOMNodePayload(APIPayloadModel):
    dom_node_id: str
    role: str
    text: str
    visible: bool
    enabled: bool
    z_index: int
    bbox: BBoxPayload


class DecideRequest(APIPayloadModel):
    entities: list[UIEntityPayload]
    dom_nodes: list[DOMNodePayload]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entities": [
                    {
                        "entity_id": "e1",
                        "label": "Search",
                        "role": "button",
                        "text": "Search Flights",
                        "confidence": 0.91,
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
                        "z_index": 10,
                        "bbox": {"x": 102, "y": 101, "width": 120, "height": 40},
                    }
                ],
            }
        }
    )


class DecideResponse(APIPayloadModel):
    status: str
    state: str
    dom_node_id: str | None = None
    x: int | None = None
    y: int | None = None
    score: float | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "state": "complete",
                "dom_node_id": "search-btn",
                "x": 162,
                "y": 121,
                "score": 0.93,
            }
        }
    )


class APIErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REQUEST_VALIDATION_ERROR = "REQUEST_VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_CONFLICT = "SESSION_CONFLICT"
    API_DEPRECATED = "API_DEPRECATED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class APIError(APIPayloadModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: list[dict[str, Any]] = Field(default_factory=list)


class APIErrorResponse(APIPayloadModel):
    error: APIError


class DeprecationPolicyResponse(APIPayloadModel):
    replacement_prefix: str
    deprecated_prefix: str
    sunset: str
    policy: str


API_V1_PREFIX = "/api/v1"
LEGACY_PREFIX = ""
LEGACY_SUNSET_DATE = "2026-06-30"
DEPRECATION_DOC_PATH = f"{API_V1_PREFIX}/deprecations"


def create_app() -> FastAPI:
    app = FastAPI(title="Project Mimic API", version="0.1.0")
    session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
    scavenger_interval_seconds = int(os.getenv("SESSION_SCAVENGER_INTERVAL_SECONDS", "5"))
    auth_keys = {item.strip() for item in os.getenv("API_AUTH_KEYS", "").split(",") if item.strip()}
    role_rank = {"viewer": 1, "operator": 2, "admin": 3}
    default_role = os.getenv("API_AUTH_DEFAULT_ROLE", "operator").strip().lower()
    if default_role not in role_rank:
        default_role = "operator"

    role_map: dict[str, str] = {}
    for pair in os.getenv("API_AUTH_ROLE_MAP", "").split(","):
        cleaned = pair.strip()
        if not cleaned or ":" not in cleaned:
            continue
        key, role = cleaned.split(":", 1)
        key = key.strip()
        role = role.strip().lower()
        if key and role in role_rank:
            role_map[key] = role

    registry = SessionRegistry(ttl_seconds=session_ttl_seconds)
    api_tracer = OpenTelemetryTracer(component="api")
    orchestrator_tracer = OpenTelemetryTracer(component="orchestrator")
    engine = ExecutionEngine(orchestrator=DecisionOrchestrator(tracer=orchestrator_tracer))
    metrics = InMemoryMetrics()
    scavenger_stop = Event()
    scavenger_thread: Thread | None = None

    def _set_deprecation_headers(response: Response) -> None:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = LEGACY_SUNSET_DATE
        response.headers["Link"] = f"<{DEPRECATION_DOC_PATH}>; rel=\"deprecation\""

    def _is_auth_exempt_path(path: str) -> bool:
        if path in {"/openapi.json", "/docs/oauth2-redirect"}:
            return True
        return path.startswith("/docs") or path == "/redoc"

    def _required_role_for_method(method: str) -> str:
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            return "operator"
        return "viewer"

    def _error_response(
        request: Request,
        *,
        status_code: int,
        code: APIErrorCode | str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "request_id", None)
        safe_message = redact_sensitive_text(message)
        payload = APIErrorResponse(
            error=APIError(
                code=code.value if isinstance(code, APIErrorCode) else str(code),
                message=safe_message,
                correlation_id=correlation_id,
                details=redact_sensitive_structure(details or []),
            )
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    def _resolve_http_code(exc: HTTPException) -> APIErrorCode:
        detail = str(exc.detail).lower()
        if exc.status_code == 404 and "session" in detail:
            return APIErrorCode.SESSION_NOT_FOUND
        if exc.status_code == 410:
            return APIErrorCode.SESSION_EXPIRED
        if exc.status_code == 409:
            return APIErrorCode.SESSION_CONFLICT
        if exc.status_code == 422:
            return APIErrorCode.VALIDATION_ERROR
        return APIErrorCode.INTERNAL_ERROR

    def _create_session(payload: CreateSessionRequest) -> SessionCreatedResponse:
        session_id, observation = registry.create(goal=payload.goal, max_steps=payload.max_steps)
        return SessionCreatedResponse(session_id=session_id, observation=observation)

    def _reset_session(session_id: str, payload: ResetSessionRequest) -> Observation:
        try:
            return registry.reset(session_id=session_id, goal=payload.goal)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except InvalidSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    def _step_session(session_id: str, action: UIAction) -> StepResponse:
        try:
            env = registry.get(session_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        try:
            observation, reward, done, info = env.step(action)
            if done:
                registry.mark_completed(session_id)
            else:
                registry.save_checkpoint(session_id)
        except RuntimeError as exc:
            registry.mark_failed(session_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return StepResponse(observation=observation, reward=reward, done=done, info=info)

    def _state_session(session_id: str) -> dict[str, Any]:
        try:
            env = registry.get(session_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        return env.state()

    def _list_sessions(
        status: str | None,
        goal_contains: str | None,
        created_after: float | None,
        created_before: float | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
    ) -> SessionListResponse:
        filter_status = SessionStatus(status) if status else None
        result = registry.list_sessions(
            status=filter_status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )
        return SessionListResponse(**result)

    def _restore_session(session_id: str) -> dict[str, Any]:
        try:
            return registry.restore(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="checkpoint not found") from exc

    def _rollback_session(session_id: str) -> dict[str, Any]:
        try:
            return registry.rollback_to_checkpoint(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _resume_session(session_id: str) -> dict[str, Any]:
        try:
            return registry.resume_from_checkpoint(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _decide_click(payload: DecideRequest) -> DecideResponse:
        entities = [
            UIEntity(
                entity_id=item.entity_id,
                label=item.label,
                role=item.role,
                text=item.text,
                confidence=item.confidence,
                bbox=BBox(
                    x=item.bbox.x,
                    y=item.bbox.y,
                    width=item.bbox.width,
                    height=item.bbox.height,
                ),
            )
            for item in payload.entities
        ]

        dom_nodes = [
            DOMNode(
                dom_node_id=item.dom_node_id,
                role=item.role,
                text=item.text,
                visible=item.visible,
                enabled=item.enabled,
                z_index=item.z_index,
                bbox=BBox(
                    x=item.bbox.x,
                    y=item.bbox.y,
                    width=item.bbox.width,
                    height=item.bbox.height,
                ),
            )
            for item in payload.dom_nodes
        ]

        decision = engine.decide_coordinate_click(entities=entities, dom_nodes=dom_nodes)
        return DecideResponse(
            status=decision.status,
            state=decision.state.value,
            dom_node_id=decision.dom_node_id,
            x=decision.x,
            y=decision.y,
            score=decision.score,
        )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id

        if auth_keys and not _is_auth_exempt_path(request.url.path):
            provided_key = request.headers.get("x-api-key", "")
            if provided_key not in auth_keys:
                unauthorized_response = _error_response(
                    request,
                    status_code=401,
                    code=APIErrorCode.UNAUTHORIZED,
                    message="missing or invalid api key",
                )
                unauthorized_response.headers["WWW-Authenticate"] = "ApiKey"
                unauthorized_response.headers["X-Request-ID"] = request_id
                unauthorized_response.headers["X-Correlation-ID"] = request_id
                return unauthorized_response

            caller_role = role_map.get(provided_key, default_role)
            required_role = _required_role_for_method(request.method)
            if role_rank[caller_role] < role_rank[required_role]:
                forbidden_response = _error_response(
                    request,
                    status_code=403,
                    code=APIErrorCode.FORBIDDEN,
                    message="role does not permit this operation",
                )
                forbidden_response.headers["X-Request-ID"] = request_id
                forbidden_response.headers["X-Correlation-ID"] = request_id
                return forbidden_response

        start = time.perf_counter()
        with api_tracer.start_span(
            "api.request",
            trace_id=request_id,
            attributes={"path": request.url.path, "method": request.method},
        ):
            response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.record(request.url.path, response.status_code, elapsed_ms)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        return _error_response(
            request,
            status_code=422,
            code=APIErrorCode.REQUEST_VALIDATION_ERROR,
            message="request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        envelope = map_exception_to_error(exc)
        return _error_response(
            request,
            status_code=422,
            code=envelope.code.value,
            message=envelope.message,
            details=envelope.details,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return _error_response(
            request,
            status_code=exc.status_code,
            code=_resolve_http_code(exc),
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def uncaught_exception_handler(request: Request, exc: Exception):
        return _error_response(
            request,
            status_code=500,
            code=APIErrorCode.INTERNAL_ERROR,
            message=str(exc),
        )

    @app.on_event("startup")
    def startup_scavenger() -> None:
        def _loop() -> None:
            while not scavenger_stop.wait(scavenger_interval_seconds):
                registry.scavenge_expired()

        nonlocal scavenger_thread
        scavenger_thread = Thread(target=_loop, daemon=True, name="session-scavenger")
        scavenger_thread.start()

    @app.on_event("shutdown")
    def shutdown_scavenger() -> None:
        scavenger_stop.set()
        if scavenger_thread and scavenger_thread.is_alive():
            scavenger_thread.join(timeout=1.0)

    @app.get(DEPRECATION_DOC_PATH, response_model=DeprecationPolicyResponse)
    def deprecation_policy() -> DeprecationPolicyResponse:
        return DeprecationPolicyResponse(
            replacement_prefix=API_V1_PREFIX,
            deprecated_prefix=LEGACY_PREFIX,
            sunset=LEGACY_SUNSET_DATE,
            policy="Unversioned endpoints are supported for compatibility only and include deprecation headers.",
        )

    @app.post(f"{API_V1_PREFIX}/sessions", response_model=SessionCreatedResponse)
    def create_session_v1(payload: CreateSessionRequest, request: Request) -> SessionCreatedResponse:
        response = _create_session(payload)
        metrics.record_feature_result(
            "session.create",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=payload.goal,
            action_type="create",
        )
        return response

    @app.post("/sessions", response_model=SessionCreatedResponse, deprecated=True)
    def create_session_legacy(
        payload: CreateSessionRequest,
        response: Response,
        request: Request,
    ) -> SessionCreatedResponse:
        _set_deprecation_headers(response)
        created = _create_session(payload)
        metrics.record_feature_result(
            "session.create",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=payload.goal,
            action_type="create",
        )
        return created

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/reset", response_model=Observation)
    def reset_session_v1(session_id: str, payload: ResetSessionRequest) -> Observation:
        return _reset_session(session_id, payload)

    @app.post("/sessions/{session_id}/reset", response_model=Observation, deprecated=True)
    def reset_session_legacy(session_id: str, payload: ResetSessionRequest, response: Response) -> Observation:
        _set_deprecation_headers(response)
        return _reset_session(session_id, payload)

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/step", response_model=StepResponse)
    def step_session_v1(session_id: str, action: UIAction, request: Request) -> StepResponse:
        response = _step_session(session_id, action)
        goal = response.observation.goal
        metrics.record_feature_result(
            "session.step",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=goal,
            action_type=action.action_type.value,
        )
        return response

    @app.post("/sessions/{session_id}/step", response_model=StepResponse, deprecated=True)
    def step_session_legacy(
        session_id: str,
        action: UIAction,
        response: Response,
        request: Request,
    ) -> StepResponse:
        _set_deprecation_headers(response)
        step_response = _step_session(session_id, action)
        metrics.record_feature_result(
            "session.step",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=step_response.observation.goal,
            action_type=action.action_type.value,
        )
        return step_response

    @app.get(f"{API_V1_PREFIX}/sessions/{{session_id}}/state")
    def state_session_v1(session_id: str) -> dict[str, Any]:
        return _state_session(session_id)

    @app.get("/sessions/{session_id}/state", deprecated=True)
    def state_session_legacy(session_id: str, response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _state_session(session_id)

    @app.get(f"{API_V1_PREFIX}/sessions", response_model=SessionListResponse)
    def list_sessions_v1(
        status: str | None = Query(default=None),
        goal_contains: str | None = Query(default=None, min_length=1),
        created_after: float | None = Query(default=None, ge=0),
        created_before: float | None = Query(default=None, ge=0),
        sort_by: str = Query(default="created_at"),
        sort_order: str = Query(default="desc"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> SessionListResponse:
        return _list_sessions(
            status=status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )

    @app.get("/sessions", response_model=SessionListResponse, deprecated=True)
    def list_sessions_legacy(
        response: Response,
        status: str | None = Query(default=None),
        goal_contains: str | None = Query(default=None, min_length=1),
        created_after: float | None = Query(default=None, ge=0),
        created_before: float | None = Query(default=None, ge=0),
        sort_by: str = Query(default="created_at"),
        sort_order: str = Query(default="desc"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> SessionListResponse:
        _set_deprecation_headers(response)
        return _list_sessions(
            status=status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )

    @app.get(f"{API_V1_PREFIX}/sessions/{{session_id}}/restore")
    def restore_session_v1(session_id: str) -> dict[str, Any]:
        return _restore_session(session_id)

    @app.get("/sessions/{session_id}/restore", deprecated=True)
    def restore_session_legacy(session_id: str, response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _restore_session(session_id)

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/rollback")
    def rollback_session_v1(session_id: str) -> dict[str, Any]:
        return _rollback_session(session_id)

    @app.post("/sessions/{session_id}/rollback", deprecated=True)
    def rollback_session_legacy(session_id: str, response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _rollback_session(session_id)

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/resume")
    def resume_session_v1(session_id: str) -> dict[str, Any]:
        return _resume_session(session_id)

    @app.post("/sessions/{session_id}/resume", deprecated=True)
    def resume_session_legacy(session_id: str, response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _resume_session(session_id)

    @app.post(
        f"{API_V1_PREFIX}/decision/click",
        response_model=DecideResponse,
        openapi_extra={
            "responses": {
                "200": {
                    "description": "Best click candidate chosen from grounded entities",
                    "content": {
                        "application/json": {
                            "example": {
                                "status": "ok",
                                "state": "complete",
                                "dom_node_id": "search-btn",
                                "x": 162,
                                "y": 121,
                                "score": 0.93,
                            }
                        }
                    },
                }
            }
        },
    )
    def decide_click_v1(payload: DecideRequest, request: Request) -> DecideResponse:
        response = _decide_click(payload)
        metrics.record_feature_result(
            "orchestrator.decision",
            success=response.status == "ok",
            trace_id=getattr(request.state, "request_id", None),
            action_type="click",
        )
        return response

    @app.post("/decision/click", response_model=DecideResponse, deprecated=True)
    def decide_click_legacy(payload: DecideRequest, response: Response, request: Request) -> DecideResponse:
        _set_deprecation_headers(response)
        decide_response = _decide_click(payload)
        metrics.record_feature_result(
            "orchestrator.decision",
            success=decide_response.status == "ok",
            trace_id=getattr(request.state, "request_id", None),
            action_type="click",
        )
        return decide_response

    @app.get(f"{API_V1_PREFIX}/metrics")
    def get_metrics_v1() -> dict[str, Any]:
        snapshot = metrics.snapshot()
        snapshot["traces"] = {
            "api": api_tracer.trace_snapshot(),
            "orchestrator": orchestrator_tracer.trace_snapshot(),
        }
        return snapshot

    @app.get("/metrics", deprecated=True)
    def get_metrics_legacy(response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        snapshot = metrics.snapshot()
        snapshot["traces"] = {
            "api": api_tracer.trace_snapshot(),
            "orchestrator": orchestrator_tracer.trace_snapshot(),
        }
        return snapshot

    return app


app = create_app()
