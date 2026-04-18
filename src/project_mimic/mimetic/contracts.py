"""Typed contracts and adapters for Rust<->Python mimetic event streams."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, model_validator

from project_mimic.models import ProjectMimicModel

EventChannel = Literal["pointer", "keyboard"]


class MimeticEvent(ProjectMimicModel):
    """Single low-level interaction event emitted by mimetic planners."""

    t_ms: int = Field(ge=0)
    event_type: str
    x: float | None = None
    y: float | None = None
    key: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "MimeticEvent":
        pointer_events = {"move", "down", "up"}
        key_events = {"keydown", "keyup", "backspace"}

        if self.event_type in pointer_events:
            if self.x is None or self.y is None:
                raise ValueError("pointer events require x and y coordinates")
            if self.key is not None:
                raise ValueError("pointer events cannot set key")
            return self

        if self.event_type in key_events:
            if self.key is None:
                raise ValueError("keyboard events require key")
            if self.x is not None or self.y is not None:
                raise ValueError("keyboard events cannot set x/y")
            return self

        raise ValueError(f"unsupported mimetic event type: {self.event_type}")


class MimeticEventStream(ProjectMimicModel):
    """Versioned stream contract exchanged between Rust and Python layers."""

    schema_version: str = "1.0"
    source: str = "rust-mimetic"
    channel: EventChannel
    profile: str
    deterministic_seed: int | None = None
    events: list[MimeticEvent] = Field(default_factory=list)


class RustPythonEventBridge:
    """Bridge adapter for parsing and serializing gRPC events_json payloads."""

    @staticmethod
    def from_rust_events(
        events_json: list[str],
        *,
        channel: EventChannel,
        profile: str,
        deterministic_seed: int | None = None,
    ) -> MimeticEventStream:
        events: list[MimeticEvent] = []
        for payload in events_json:
            parsed = json.loads(payload)
            events.append(MimeticEvent.model_validate(parsed))

        return MimeticEventStream(
            channel=channel,
            profile=profile,
            deterministic_seed=deterministic_seed,
            events=events,
        )

    @staticmethod
    def to_grpc_payload(stream: MimeticEventStream) -> list[str]:
        return [event.model_dump_json(exclude_none=True) for event in stream.events]
