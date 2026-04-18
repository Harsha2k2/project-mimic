from project_mimic.policy import PolicyContext, PolicyEngine, PolicyRuleOutcome


def test_policy_denies_when_not_authorized() -> None:
    engine = PolicyEngine()
    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=False,
            risk_score=0.1,
            action="click",
        )
    )
    assert decision.allowed is False
    assert decision.reason == "missing authorization"


def test_policy_denies_when_risk_exceeds_threshold() -> None:
    engine = PolicyEngine(risk_threshold=0.6)
    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.9,
            action="click",
        )
    )
    assert decision.allowed is False
    assert decision.reason == "risk threshold exceeded"


def test_policy_allows_safe_action() -> None:
    engine = PolicyEngine(risk_threshold=0.6)
    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.2,
            action="click",
        )
    )
    assert decision.allowed is True
    assert decision.reason == "allowed"


def test_policy_rule_registry_honors_priority_ordering() -> None:
    engine = PolicyEngine(risk_threshold=0.9)

    def allow_rule(_: PolicyContext) -> PolicyRuleOutcome:
        return PolicyRuleOutcome(decision=True, reason="allowed by custom rule")

    def deny_rule(_: PolicyContext) -> PolicyRuleOutcome:
        return PolicyRuleOutcome(decision=False, reason="denied by higher priority rule")

    engine.register_rule(
        "custom_allow",
        priority=10,
        description="lower priority allow",
        evaluator=allow_rule,
    )
    engine.register_rule(
        "custom_deny",
        priority=110,
        description="higher priority deny",
        evaluator=deny_rule,
    )

    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.1,
            action="click",
        )
    )
    assert decision.allowed is False
    assert decision.applied_rule_id == "custom_deny"


def test_policy_simulation_mode_does_not_enforce_denial() -> None:
    engine = PolicyEngine(risk_threshold=0.4)
    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.95,
            action="click",
        ),
        simulate=True,
    )

    assert decision.simulated is True
    assert decision.allowed is True
    assert decision.would_allow is False


def test_jurisdiction_override_supports_policy_exceptions() -> None:
    engine = PolicyEngine(risk_threshold=0.2)
    engine.set_jurisdiction_override(
        "eu-test",
        "risk_threshold",
        action="allow",
        reason="regulatory exception for supervised workflows",
    )

    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.9,
            action="click",
            jurisdiction="eu-test",
        )
    )
    assert decision.allowed is True
    assert decision.applied_rule_id == "risk_threshold"


def test_policy_decision_includes_explanations_for_audit() -> None:
    engine = PolicyEngine(risk_threshold=0.6)
    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-1",
            site_id="site-a",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.1,
            action="click",
        ),
        simulate=True,
    )

    assert decision.explanations
    assert any(item.rule_id == "authorization_required" for item in decision.explanations)


def test_conflicting_policy_resolution_prefers_higher_priority_rule() -> None:
    engine = PolicyEngine(risk_threshold=0.9)

    engine.register_rule(
        "deny_conflict",
        priority=120,
        description="high priority deny",
        evaluator=lambda _: PolicyRuleOutcome(decision=False, reason="deny conflict"),
    )
    engine.register_rule(
        "allow_conflict",
        priority=30,
        description="lower priority allow",
        evaluator=lambda _: PolicyRuleOutcome(decision=True, reason="allow conflict"),
    )

    decision = engine.evaluate(
        PolicyContext(
            actor_id="agent-2",
            site_id="site-b",
            region_allowed=True,
            has_authorization=True,
            risk_score=0.1,
            action="click",
        )
    )
    assert decision.allowed is False
    assert decision.applied_rule_id == "deny_conflict"
