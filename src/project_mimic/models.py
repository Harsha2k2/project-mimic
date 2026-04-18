"""Typed contracts for Project Mimic environment interactions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectMimicModel(BaseModel):
    """Shared strict model config for public payload contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ActionType(str, Enum):
    """Supported baseline action categories."""

    CLICK = "click"
    TYPE = "type"
    WAIT = "wait"


class UIAction(ProjectMimicModel):
    """Input action requested by the high-level agent."""

    schema_version: str = "1.0"
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


class Observation(ProjectMimicModel):
    """Observation returned after reset and step operations."""

    schema_version: str = "1.0"
    step_index: int = Field(ge=0)
    goal: str
    status: str
    url: str | None = None
    last_event: str | None = None
    screenshot_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Reward(ProjectMimicModel):
    """Reward object with score and reason for explainability."""

    schema_version: str = "1.0"
    score: float = Field(ge=0.0)
    reason: str


class ErrorCode(str, Enum):
    """Machine-readable model error codes."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    PAYLOAD_CONSTRAINT_VIOLATION = "PAYLOAD_CONSTRAINT_VIOLATION"
    SERIALIZATION_ERROR = "SERIALIZATION_ERROR"
