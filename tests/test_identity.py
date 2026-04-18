from project_mimic.identity import (
    IdentityAllocator,
    ProxyEndpoint,
    RiskSignals,
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
    ]


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
