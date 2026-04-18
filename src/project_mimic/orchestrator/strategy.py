"""Pluggable strategy interfaces for site-specific decision behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decision_orchestrator import ActionCandidate


class OrchestrationStrategy:
    """Strategy contract for calibrating and scoring candidates per site."""

    def calibrate_confidence(self, candidate: "ActionCandidate", signal_quality: float) -> float:
        return candidate.confidence

    def fallback_score(self, candidate: "ActionCandidate") -> float:
        return candidate.score()


@dataclass
class SiteStrategyRegistry:
    default_strategy: OrchestrationStrategy

    def __post_init__(self) -> None:
        self._site_strategies: dict[str, OrchestrationStrategy] = {}

    def register(self, site_id: str, strategy: OrchestrationStrategy) -> None:
        self._site_strategies[site_id] = strategy

    def resolve(self, site_id: str | None) -> OrchestrationStrategy:
        if not site_id:
            return self.default_strategy
        return self._site_strategies.get(site_id, self.default_strategy)
