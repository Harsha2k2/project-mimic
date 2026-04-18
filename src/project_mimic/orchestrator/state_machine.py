"""Action-level state machine for observe -> execute -> verify flow."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionState(str, Enum):
    OBSERVE = "observe"
    HYPOTHESIZE = "hypothesize"
    GROUND = "ground"
    PLAN_MOTION = "plan_motion"
    EXECUTE = "execute"
    VERIFY = "verify"
    RECOVER = "recover"
    COMPLETE = "complete"
    FAIL = "fail"


@dataclass
class StepSignal:
    frame_ready: bool = False
    intent_confident: bool = False
    target_resolved: bool = False
    motion_planned: bool = False
    events_ack: bool = False
    verify_ok: bool = False


class ActionStateMachine:
    """Bounded-retry state machine for a single action lifecycle."""

    def __init__(self, max_retries: int = 2) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")

        self.max_retries = max_retries
        self.retry_count = 0
        self.state = ActionState.OBSERVE
        self.history: list[ActionState] = [self.state]

    def reset(self) -> None:
        self.retry_count = 0
        self.state = ActionState.OBSERVE
        self.history = [self.state]

    def apply(self, signal: StepSignal) -> ActionState:
        if self.state in (ActionState.COMPLETE, ActionState.FAIL):
            return self.state

        if self.state == ActionState.OBSERVE:
            self._transition(ActionState.HYPOTHESIZE if signal.frame_ready else ActionState.OBSERVE)
            return self.state

        if self.state == ActionState.HYPOTHESIZE:
            self._transition(ActionState.GROUND if signal.intent_confident else ActionState.RECOVER)
            return self.state

        if self.state == ActionState.GROUND:
            self._transition(ActionState.PLAN_MOTION if signal.target_resolved else ActionState.RECOVER)
            return self.state

        if self.state == ActionState.PLAN_MOTION:
            self._transition(ActionState.EXECUTE if signal.motion_planned else ActionState.RECOVER)
            return self.state

        if self.state == ActionState.EXECUTE:
            self._transition(ActionState.VERIFY if signal.events_ack else ActionState.RECOVER)
            return self.state

        if self.state == ActionState.VERIFY:
            self._transition(ActionState.COMPLETE if signal.verify_ok else ActionState.RECOVER)
            return self.state

        if self.state == ActionState.RECOVER:
            if self.retry_count < self.max_retries:
                self.retry_count += 1
                self._transition(ActionState.OBSERVE)
            else:
                self._transition(ActionState.FAIL)
            return self.state

        return self.state

    def is_terminal(self) -> bool:
        return self.state in (ActionState.COMPLETE, ActionState.FAIL)

    def _transition(self, next_state: ActionState) -> None:
        if next_state != self.state:
            self.state = next_state
            self.history.append(next_state)
