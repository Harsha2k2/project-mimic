from project_mimic.identity import (
    IdentityAllocator,
    InMemoryProxyPoolStore,
    ProxyEndpoint,
    RiskSignals,
    RotationReason,
    calculate_risk_score,
    should_rotate_identity,
)


def _sample_proxies() -> list[ProxyEndpoint]:
    return [
        ProxyEndpoint(
            endpoint_id="p1",
            host="1.1.1.1",
            port=8000,
            region="us-east",
            asn_class="residential",
            health_score=0.9,
        ),
        ProxyEndpoint(
            endpoint_id="p2",
            host="2.2.2.2",
            port=8000,
            region="eu-central",
            asn_class="residential",
            health_score=0.8,
        ),
        ProxyEndpoint(
            endpoint_id="p3",
            host="3.3.3.3",
            port=8000,
            region="us-east",
            asn_class="residential",
            health_score=0.75,
        ),
    ]


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now_value = start

    def now(self) -> float:
        return self.now_value

    def advance(self, seconds: float) -> None:
        self.now_value += seconds


def test_allocator_produces_coherent_bundle() -> None:
    allocator = IdentityAllocator(_sample_proxies())
    bundle = allocator.allocate(session_id="s1", behavior_profile_id="profile-a")

    assert bundle.proxy.endpoint_id == "p1"
    assert bundle.locale == "en_US"
    assert bundle.language == "en"
    assert bundle.behavior_profile_id == "profile-a"


def test_rotate_uses_different_proxy_when_available() -> None:
    allocator = IdentityAllocator(_sample_proxies())
    current = allocator.allocate(session_id="s1", behavior_profile_id="profile-a")
    rotated = allocator.rotate(current, session_id="s1", behavior_profile_id="profile-a")

    assert rotated.proxy.endpoint_id != current.proxy.endpoint_id


def test_risk_score_and_rotation_threshold() -> None:
    low = RiskSignals(challenge_rate=0.1, network_error_rate=0.1, rejection_rate=0.1)
    high = RiskSignals(
        challenge_rate=0.9,
        network_error_rate=0.7,
        rejection_rate=0.8,
        fingerprint_mismatch=True,
    )

    assert calculate_risk_score(high) > calculate_risk_score(low)
    assert should_rotate_identity(low, threshold=0.6) is False
    assert should_rotate_identity(high, threshold=0.6) is True


def test_proxy_pool_persistence_keeps_health_history() -> None:
    store = InMemoryProxyPoolStore()
    allocator = IdentityAllocator(_sample_proxies(), store=store)

    allocator.record_proxy_health("p1", success=False, latency_ms=900, reason="timeout")
    allocator.record_proxy_health("p1", success=True, latency_ms=220, reason="recovered")

    restored = IdentityAllocator(_sample_proxies(), store=store)
    history = restored.get_proxy_health_history("p1")
    assert len(history) == 2
    assert history[0].reason == "timeout"
    assert history[1].reason == "recovered"


def test_weighted_allocator_penalizes_failure_rate() -> None:
    allocator = IdentityAllocator(
        _sample_proxies(),
        region_weights={"us-east": 1.0, "eu-central": 1.1},
    )

    # Repeated failures lower effective weight for p1.
    allocator.record_proxy_health("p1", success=False, reason="blocked")
    allocator.record_proxy_health("p1", success=False, reason="blocked")
    allocator.record_proxy_health("p1", success=False, reason="blocked")

    bundle = allocator.allocate(session_id="weighted-1", behavior_profile_id="profile-a")
    assert bundle.proxy.endpoint_id != "p1"


def test_sticky_identity_respected_until_cooldown_expiry() -> None:
    clock = _Clock()
    allocator = IdentityAllocator(
        _sample_proxies(),
        now_fn=clock.now,
        sticky_window_seconds=20,
    )

    first = allocator.allocate(session_id="sticky-1", behavior_profile_id="profile-a")
    second = allocator.allocate(session_id="sticky-1", behavior_profile_id="profile-a")
    assert first.proxy.endpoint_id == second.proxy.endpoint_id

    clock.advance(25)
    third = allocator.allocate(session_id="sticky-1", behavior_profile_id="profile-a")
    assert third.proxy.endpoint_id in {"p1", "p2", "p3"}


def test_rotation_audit_trail_records_reason_codes() -> None:
    allocator = IdentityAllocator(_sample_proxies())
    current = allocator.allocate(session_id="audit-1", behavior_profile_id="profile-a")

    rotated = allocator.rotate(
        current,
        session_id="audit-1",
        behavior_profile_id="profile-a",
        reason=RotationReason.RISK_THRESHOLD,
        risk_score=0.83,
    )
    assert rotated.proxy.endpoint_id != current.proxy.endpoint_id

    audit = allocator.rotation_audit_log()
    assert len(audit) == 1
    assert audit[0].reason_code == RotationReason.RISK_THRESHOLD
    assert audit[0].risk_score == 0.83


def test_proxy_quarantine_and_unquarantine_flow() -> None:
    clock = _Clock()
    allocator = IdentityAllocator(_sample_proxies(), now_fn=clock.now)

    allocator.quarantine_proxy("p1", duration_seconds=10, reason="error spike")
    assert allocator.is_quarantined("p1") is True

    allocated = allocator.allocate(session_id="q-1", behavior_profile_id="profile-a")
    assert allocated.proxy.endpoint_id != "p1"

    clock.advance(11)
    released = allocator.unquarantine_expired()
    assert released >= 1
    assert allocator.is_quarantined("p1") is False
