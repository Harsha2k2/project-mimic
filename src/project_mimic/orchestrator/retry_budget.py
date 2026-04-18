"""Retry budget manager with per-state caps."""

from __future__ import annotations

from dataclasses import dataclass, field

from .state_machine import ActionState


@dataclass
class RetryBudgetManager:
    per_state_caps: dict[ActionState, int]
    usage: dict[ActionState, int] = field(default_factory=dict)

    def consume(self, state: ActionState) -> bool:
        cap = self.per_state_caps.get(state)
        if cap is None:
            return True

        current = self.usage.get(state, 0)
        if current >= cap:
            return False

        self.usage[state] = current + 1
        return True

    def reset(self) -> None:
        self.usage.clear()
