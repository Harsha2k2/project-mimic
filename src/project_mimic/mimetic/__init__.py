"""Mimetic event synthesis contracts and planners."""

from .contracts import MimeticEvent, MimeticEventStream, RustPythonEventBridge
from .planner import TypoCorrectionStrategy, plan_pointer_stream, synthesize_typing_stream
from .profiles import JitterProfile, MovementProfile, jitter_profile_for_device, movement_profile_for_viewport

__all__ = [
    "JitterProfile",
    "MimeticEvent",
    "MimeticEventStream",
    "MovementProfile",
    "RustPythonEventBridge",
    "TypoCorrectionStrategy",
    "jitter_profile_for_device",
    "movement_profile_for_viewport",
    "plan_pointer_stream",
    "synthesize_typing_stream",
]
