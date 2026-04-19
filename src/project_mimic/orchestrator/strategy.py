"""Pluggable strategy interfaces for site-specific decision behavior."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
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

    def register_class(self, site_id: str, strategy_class: str) -> None:
        class_path = strategy_class.strip()
        if not class_path:
            raise ValueError("strategy_class must not be empty")
        if "." not in class_path:
            raise ValueError("strategy_class must include module and class name")

        module_name, class_name = class_path.rsplit(".", 1)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise ValueError(f"unable to import strategy module: {module_name}") from exc

        try:
            strategy_type = getattr(module, class_name)
        except AttributeError as exc:
            raise ValueError(f"strategy class not found: {class_path}") from exc

        if not isinstance(strategy_type, type):
            raise ValueError("strategy_class does not resolve to a class")
        if not issubclass(strategy_type, OrchestrationStrategy):
            raise ValueError("strategy_class must inherit OrchestrationStrategy")

        try:
            instance = strategy_type()
        except Exception as exc:
            raise ValueError(f"unable to instantiate strategy class: {class_path}") from exc

        self.register(site_id=site_id, strategy=instance)

    def strategy_mapping(self) -> dict[str, str]:
        return {
            site_id: f"{strategy.__class__.__module__}.{strategy.__class__.__name__}"
            for site_id, strategy in self._site_strategies.items()
        }

    def resolve(self, site_id: str | None) -> OrchestrationStrategy:
        if not site_id:
            return self.default_strategy
        return self._site_strategies.get(site_id, self.default_strategy)
