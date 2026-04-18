"""Policy engine for execution safety and compliance gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class PolicyContext:
    actor_id: str
    site_id: str
    region_allowed: bool
    has_authorization: bool
    risk_score: float
    action: str
    jurisdiction: str = "global"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyRuleOutcome:
    decision: bool | None
    reason: str


PolicyRuleEvaluator = Callable[[PolicyContext], PolicyRuleOutcome]


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    priority: int
    description: str
    evaluator: PolicyRuleEvaluator


@dataclass(frozen=True)
class PolicyExplanation:
    rule_id: str
    priority: int
    verdict: str
    reason: str


@dataclass(frozen=True)
class JurisdictionOverride:
    action: str
    reason: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    applied_rule_id: str | None = None
    simulated: bool = False
    would_allow: bool | None = None
    explanations: list[PolicyExplanation] = field(default_factory=list)


class PolicyEngine:
    def __init__(self, risk_threshold: float = 0.7) -> None:
        if not 0.0 <= risk_threshold <= 1.0:
            raise ValueError("risk_threshold must be in [0.0, 1.0]")
        self.risk_threshold = risk_threshold
        self._rules: list[PolicyRule] = []
        self._overrides: dict[str, dict[str, JurisdictionOverride]] = {}
        self._register_default_rules()

    def register_rule(
        self,
        rule_id: str,
        *,
        priority: int,
        description: str,
        evaluator: PolicyRuleEvaluator,
    ) -> None:
        if not rule_id.strip():
            raise ValueError("rule_id must not be empty")

        self._rules = [rule for rule in self._rules if rule.rule_id != rule_id]
        self._rules.append(
            PolicyRule(
                rule_id=rule_id,
                priority=priority,
                description=description,
                evaluator=evaluator,
            )
        )
        self._rules.sort(key=lambda rule: rule.priority, reverse=True)

    def set_jurisdiction_override(self, jurisdiction: str, rule_id: str, *, action: str, reason: str) -> None:
        normalized_action = action.lower()
        if normalized_action not in {"allow", "deny", "skip"}:
            raise ValueError("override action must be allow, deny, or skip")
        if not jurisdiction.strip():
            raise ValueError("jurisdiction must not be empty")

        bucket = self._overrides.setdefault(jurisdiction, {})
        bucket[rule_id] = JurisdictionOverride(action=normalized_action, reason=reason)

    def evaluate(self, context: PolicyContext, *, simulate: bool = False) -> PolicyDecision:
        explanations: list[PolicyExplanation] = []
        simulated_would_allow = True
        winning_rule_id: str | None = None
        winning_reason = "allowed"

        for rule in self._rules:
            override = self._overrides.get(context.jurisdiction, {}).get(rule.rule_id)
            if override is not None:
                verdict = f"override_{override.action}"
                explanations.append(
                    PolicyExplanation(
                        rule_id=rule.rule_id,
                        priority=rule.priority,
                        verdict=verdict,
                        reason=override.reason,
                    )
                )

                if override.action == "skip":
                    continue

                override_decision = override.action == "allow"
                if winning_rule_id is None:
                    winning_rule_id = rule.rule_id
                    winning_reason = override.reason

                if not override_decision:
                    simulated_would_allow = False

                if not simulate:
                    return PolicyDecision(
                        allowed=override_decision,
                        reason=override.reason,
                        applied_rule_id=rule.rule_id,
                        explanations=explanations,
                    )
                continue

            outcome = rule.evaluator(context)
            if outcome.decision is None:
                explanations.append(
                    PolicyExplanation(
                        rule_id=rule.rule_id,
                        priority=rule.priority,
                        verdict="pass",
                        reason=outcome.reason,
                    )
                )
                continue

            verdict = "allow" if outcome.decision else "deny"
            explanations.append(
                PolicyExplanation(
                    rule_id=rule.rule_id,
                    priority=rule.priority,
                    verdict=verdict,
                    reason=outcome.reason,
                )
            )

            if winning_rule_id is None:
                winning_rule_id = rule.rule_id
                winning_reason = outcome.reason

            if not outcome.decision:
                simulated_would_allow = False

            if not simulate:
                return PolicyDecision(
                    allowed=outcome.decision,
                    reason=outcome.reason,
                    applied_rule_id=rule.rule_id,
                    explanations=explanations,
                )

        if simulate:
            return PolicyDecision(
                allowed=True,
                reason="simulation mode: no enforcement",
                applied_rule_id=winning_rule_id,
                simulated=True,
                would_allow=simulated_would_allow,
                explanations=explanations,
            )

        return PolicyDecision(
            allowed=True,
            reason="allowed",
            applied_rule_id=winning_rule_id,
            explanations=explanations,
        )

    def _register_default_rules(self) -> None:
        self.register_rule(
            "authorization_required",
            priority=100,
            description="Request must include valid authorization",
            evaluator=self._authorization_rule,
        )
        self.register_rule(
            "region_allowed",
            priority=90,
            description="Region must be permitted by policy",
            evaluator=self._region_rule,
        )
        self.register_rule(
            "risk_threshold",
            priority=80,
            description="Risk score must stay below threshold",
            evaluator=self._risk_rule,
        )
        self.register_rule(
            "action_not_empty",
            priority=70,
            description="Action payload must be non-empty",
            evaluator=self._action_rule,
        )

    def _authorization_rule(self, context: PolicyContext) -> PolicyRuleOutcome:
        if not context.has_authorization:
            return PolicyRuleOutcome(decision=False, reason="missing authorization")
        return PolicyRuleOutcome(decision=None, reason="authorization present")

    def _region_rule(self, context: PolicyContext) -> PolicyRuleOutcome:
        if not context.region_allowed:
            return PolicyRuleOutcome(decision=False, reason="region policy denied")
        return PolicyRuleOutcome(decision=None, reason="region allowed")

    def _risk_rule(self, context: PolicyContext) -> PolicyRuleOutcome:
        if context.risk_score > self.risk_threshold:
            return PolicyRuleOutcome(decision=False, reason="risk threshold exceeded")
        return PolicyRuleOutcome(decision=None, reason="risk below threshold")

    @staticmethod
    def _action_rule(context: PolicyContext) -> PolicyRuleOutcome:
        if context.action.strip() == "":
            return PolicyRuleOutcome(decision=False, reason="empty action")
        return PolicyRuleOutcome(decision=None, reason="action present")
