"""Baseline Project Mimic environment with step/reset/state API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import ActionType, Observation, Reward, UIAction


@dataclass
class _EnvState:
    goal: str
    step_index: int = 0
    status: str = "running"
    done: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)
    last_url: str | None = None


class ProjectMimicEnv:
    """Stateful environment API for high-level agent experimentation."""

    def __init__(self, goal: str, max_steps: int = 20) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")

        self._max_steps = max_steps
        self._state = _EnvState(goal=goal)

    def reset(self, goal: str | None = None) -> Observation:
        if goal is not None:
            self._state.goal = goal

        self._state.step_index = 0
        self._state.status = "running"
        self._state.done = False
        self._state.history.clear()
        self._state.last_url = None

        return self._observation(last_event="reset")

    def step(self, action: UIAction) -> tuple[Observation, Reward, bool, dict[str, Any]]:
        if self._state.done:
            raise RuntimeError("cannot call step() on a completed episode; call reset() first")

        self._state.step_index += 1
        self._state.last_url = action.metadata.get("url")

        reward = self._score_action(action)
        if action.metadata.get("goal_completed"):
            self._state.status = "completed"
            self._state.done = True
            reward = Reward(score=reward.score + 1.0, reason="goal completed")
        elif self._state.step_index >= self._max_steps:
            self._state.status = "max_steps_reached"
            self._state.done = True

        action_record = {
            "step_index": self._state.step_index,
            "action_type": action.action_type.value,
            "target": action.target,
            "x": action.x,
            "y": action.y,
        }
        self._state.history.append(action_record)

        observation = self._observation(last_event=action.action_type.value)
        info = {
            "history_length": len(self._state.history),
            "max_steps": self._max_steps,
        }
        return observation, reward, self._state.done, info

    def state(self) -> dict[str, Any]:
        return {
            "goal": self._state.goal,
            "step_index": self._state.step_index,
            "status": self._state.status,
            "done": self._state.done,
            "history": list(self._state.history),
            "last_url": self._state.last_url,
            "max_steps": self._max_steps,
        }

    def _observation(self, last_event: str | None) -> Observation:
        return Observation(
            step_index=self._state.step_index,
            goal=self._state.goal,
            status=self._state.status,
            url=self._state.last_url,
            last_event=last_event,
            metadata={
                "history_length": len(self._state.history),
                "max_steps": self._max_steps,
            },
        )

    @staticmethod
    def _score_action(action: UIAction) -> Reward:
        if action.action_type == ActionType.CLICK:
            return Reward(score=0.10, reason="click action accepted")
        if action.action_type == ActionType.TYPE:
            text_length = len(action.text or "")
            return Reward(score=0.05 + min(text_length / 100.0, 0.15), reason="typed input")
        wait_ms = action.wait_ms or 0
        score = 0.02 if wait_ms <= 300 else 0.01
        return Reward(score=score, reason="wait action accepted")
