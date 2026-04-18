"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

from threading import Lock
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field

from .error_mapping import map_exception_to_error
from .engine import ExecutionEngine
from .environment import ProjectMimicEnv
from .models import Observation, ProjectMimicModel, Reward, UIAction
from .observability import InMemoryMetrics
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


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, ProjectMimicEnv] = {}
        self._lock = Lock()

    def create(self, goal: str, max_steps: int) -> tuple[str, Observation]:
        session_id = str(uuid4())
        env = ProjectMimicEnv(goal=goal, max_steps=max_steps)
        observation = env.reset()

        with self._lock:
            self._sessions[session_id] = env

        return session_id, observation

    def get(self, session_id: str) -> ProjectMimicEnv:
        env = self._sessions.get(session_id)
        if env is None:
            raise KeyError(session_id)
        return env


def create_app() -> FastAPI:
    app = FastAPI(title="Project Mimic API", version="0.1.0")
    registry = SessionRegistry()
    engine = ExecutionEngine()
    metrics = InMemoryMetrics()

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

    @app.post("/sessions", response_model=SessionCreatedResponse)
    def create_session(payload: CreateSessionRequest) -> SessionCreatedResponse:
        session_id, observation = registry.create(goal=payload.goal, max_steps=payload.max_steps)
        return SessionCreatedResponse(session_id=session_id, observation=observation)

    @app.post("/sessions/{session_id}/reset", response_model=Observation)
    def reset_session(session_id: str, payload: ResetSessionRequest) -> Observation:
        try:
            env = registry.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        return env.reset(goal=payload.goal)

    @app.post("/sessions/{session_id}/step", response_model=StepResponse)
    def step_session(session_id: str, action: UIAction) -> StepResponse:
        try:
            env = registry.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        try:
            observation, reward, done, info = env.step(action)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return StepResponse(observation=observation, reward=reward, done=done, info=info)

    @app.get("/sessions/{session_id}/state")
    def state_session(session_id: str) -> dict[str, Any]:
        try:
            env = registry.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        return env.state()

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
