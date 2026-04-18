"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

import os
from threading import Event, Thread
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field

from .error_mapping import map_exception_to_error
from .engine import ExecutionEngine
from .models import Observation, ProjectMimicModel, Reward, UIAction
from .observability import InMemoryMetrics
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


class DecideResponse(APIPayloadModel):
    status: str
    state: str
    dom_node_id: str | None = None
    x: int | None = None
    y: int | None = None
    score: float | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Project Mimic API", version="0.1.0")
    session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
    scavenger_interval_seconds = int(os.getenv("SESSION_SCAVENGER_INTERVAL_SECONDS", "5"))

    registry = SessionRegistry(ttl_seconds=session_ttl_seconds)
    engine = ExecutionEngine()
    metrics = InMemoryMetrics()
    scavenger_stop = Event()
    scavenger_thread: Thread | None = None

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.record(request.url.path, response.status_code, elapsed_ms)
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        envelope = map_exception_to_error(exc)
        return JSONResponse(status_code=422, content={"error": envelope.__dict__})

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

    @app.post("/sessions", response_model=SessionCreatedResponse)
    def create_session(payload: CreateSessionRequest) -> SessionCreatedResponse:
        session_id, observation = registry.create(goal=payload.goal, max_steps=payload.max_steps)
        return SessionCreatedResponse(session_id=session_id, observation=observation)

    @app.post("/sessions/{session_id}/reset", response_model=Observation)
    def reset_session(session_id: str, payload: ResetSessionRequest) -> Observation:
        try:
            return registry.reset(session_id=session_id, goal=payload.goal)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except InvalidSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.post("/sessions/{session_id}/step", response_model=StepResponse)
    def step_session(session_id: str, action: UIAction) -> StepResponse:
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

    @app.get("/sessions/{session_id}/state")
    def state_session(session_id: str) -> dict[str, Any]:
        try:
            env = registry.get(session_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        return env.state()

    @app.get("/sessions", response_model=SessionListResponse)
    def list_sessions(
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SessionListResponse:
        filter_status = SessionStatus(status) if status else None
        result = registry.list_sessions(status=filter_status, page=page, page_size=page_size)
        return SessionListResponse(**result)

    @app.get("/sessions/{session_id}/restore")
    def restore_session(session_id: str) -> dict[str, Any]:
        try:
            return registry.restore(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="checkpoint not found") from exc

    @app.post("/decision/click", response_model=DecideResponse)
    def decide_click(payload: DecideRequest) -> DecideResponse:
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

    @app.get("/metrics")
    def get_metrics() -> dict[str, Any]:
        return metrics.snapshot()

    return app


app = create_app()
