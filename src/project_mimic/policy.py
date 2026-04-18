"""Policy engine for execution safety and compliance gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyContext:
    actor_id: str
    site_id: str
    region_allowed: bool
    has_authorization: bool
    risk_score: float
    action: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    def __init__(self, risk_threshold: float = 0.7) -> None:
        if not 0.0 <= risk_threshold <= 1.0:
            raise ValueError("risk_threshold must be in [0.0, 1.0]")
        self.risk_threshold = risk_threshold

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        if not context.has_authorization:
            return PolicyDecision(allowed=False, reason="missing authorization")

        if not context.region_allowed:
            return PolicyDecision(allowed=False, reason="region policy denied")

        if context.risk_score > self.risk_threshold:
            return PolicyDecision(allowed=False, reason="risk threshold exceeded")

        if context.action.strip() == "":
            return PolicyDecision(allowed=False, reason="empty action")

        return PolicyDecision(allowed=True, reason="allowed")
