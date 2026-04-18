"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .environment import ProjectMimicEnv
from .models import Observation, Reward, UIAction


class CreateSessionRequest(BaseModel):
    goal: str
    max_steps: int = Field(default=20, ge=1)


class ResetSessionRequest(BaseModel):
    goal: str | None = None


class SessionCreatedResponse(BaseModel):
    session_id: str
    observation: Observation


class StepResponse(BaseModel):
    observation: Observation
    reward: Reward
    done: bool
    info: dict[str, Any]


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

    return app


app = create_app()
