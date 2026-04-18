from project_mimic.policy import PolicyContext, PolicyEngine


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
