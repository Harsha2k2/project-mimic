"""Typed contracts for Project Mimic environment interactions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ActionType(str, Enum):
    """Supported baseline action categories."""

    CLICK = "click"
    TYPE = "type"
    WAIT = "wait"


class UIAction(BaseModel):
    """Input action requested by the high-level agent."""

    action_type: ActionType
    target: str | None = None
    x: int | None = None
    y: int | None = None
    text: str | None = None
    wait_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "UIAction":
        if self.action_type == ActionType.CLICK:
            has_target = bool(self.target)
            has_coordinates = self.x is not None and self.y is not None
            if not has_target and not has_coordinates:
                raise ValueError("click action requires target or x/y coordinates")

        if self.action_type == ActionType.TYPE and not self.text:
            raise ValueError("type action requires non-empty text")

        return self


class Observation(BaseModel):
    """Observation returned after reset and step operations."""

    step_index: int = Field(ge=0)
    goal: str
    status: str
    url: str | None = None
    last_event: str | None = None
    screenshot_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Reward(BaseModel):
    """Reward object with score and reason for explainability."""

    score: float
    reason: str
