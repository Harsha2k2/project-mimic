"""Session identity bundle allocation and risk-based rotation logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProxyEndpoint:
    endpoint_id: str
    host: str
    port: int
    region: str
    asn_class: str
    health_score: float


@dataclass(frozen=True)
class IdentityBundle:
    bundle_id: str
    proxy: ProxyEndpoint
    timezone: str
    locale: str
    language: str
    user_agent: str
    tls_profile: str
    behavior_profile_id: str


@dataclass(frozen=True)
class RiskSignals:
    challenge_rate: float = 0.0
    network_error_rate: float = 0.0
    rejection_rate: float = 0.0
    fingerprint_mismatch: bool = False


def calculate_risk_score(signals: RiskSignals) -> float:
    mismatch_penalty = 0.35 if signals.fingerprint_mismatch else 0.0
    score = (
        0.35 * _clamp01(signals.challenge_rate)
        + 0.25 * _clamp01(signals.network_error_rate)
        + 0.25 * _clamp01(signals.rejection_rate)
        + mismatch_penalty
    )
    return _clamp01(score)


def should_rotate_identity(signals: RiskSignals, threshold: float = 0.65) -> bool:
    return calculate_risk_score(signals) >= threshold


class IdentityAllocator:
    """Allocates coherent identity bundles from healthy proxy endpoints."""

    def __init__(self, proxies: list[ProxyEndpoint]) -> None:
        if not proxies:
            raise ValueError("proxies must not be empty")
        self._proxies = proxies
        self._next_index = 0

    def allocate(self, session_id: str, behavior_profile_id: str) -> IdentityBundle:
        proxy = self._pick_best_proxy()
        bundle_id = f"bundle-{session_id}-{proxy.endpoint_id}"

        timezone = _region_to_timezone(proxy.region)
        locale = _region_to_locale(proxy.region)
        language = locale.split("_")[0]

        return IdentityBundle(
            bundle_id=bundle_id,
            proxy=proxy,
            timezone=timezone,
            locale=locale,
            language=language,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
            tls_profile="chrome_124_win10",
            behavior_profile_id=behavior_profile_id,
        )

    def rotate(self, current: IdentityBundle, session_id: str, behavior_profile_id: str) -> IdentityBundle:
        eligible = [proxy for proxy in self._proxies if proxy.endpoint_id != current.proxy.endpoint_id]
        if not eligible:
            return current

        # Temporarily switch selection pool to avoid reusing current endpoint immediately.
        original = self._proxies
        self._proxies = eligible
        try:
            return self.allocate(session_id=session_id, behavior_profile_id=behavior_profile_id)
        finally:
            self._proxies = original

    def _pick_best_proxy(self) -> ProxyEndpoint:
        ordered = sorted(self._proxies, key=lambda item: item.health_score, reverse=True)
        pick = ordered[self._next_index % len(ordered)]
        self._next_index += 1
        return pick


def _region_to_timezone(region: str) -> str:
    mapping = {
        "us-east": "America/New_York",
        "us-west": "America/Los_Angeles",
        "eu-central": "Europe/Berlin",
        "ap-south": "Asia/Kolkata",
    }
    return mapping.get(region, "UTC")


def _region_to_locale(region: str) -> str:
    mapping = {
        "us-east": "en_US",
        "us-west": "en_US",
        "eu-central": "de_DE",
        "ap-south": "en_IN",
    }
    return mapping.get(region, "en_US")


def _clamp01(value: float) -> float:
    return max(0.0, min(value, 1.0))
