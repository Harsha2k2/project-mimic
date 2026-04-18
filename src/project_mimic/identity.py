"""Session identity bundle allocation and risk-based rotation logic."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import time
from typing import Protocol


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


class RotationReason(str, Enum):
    MANUAL = "MANUAL"
    RISK_THRESHOLD = "RISK_THRESHOLD"
    PROXY_UNHEALTHY = "PROXY_UNHEALTHY"
    POLICY = "POLICY"


@dataclass(frozen=True)
class ProxyHealthEvent:
    endpoint_id: str
    timestamp: float
    success: bool
    latency_ms: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RotationAuditEvent:
    session_id: str
    from_proxy_id: str
    to_proxy_id: str
    reason_code: RotationReason
    timestamp: float
    risk_score: float | None = None


@dataclass(frozen=True)
class ProxyPoolSnapshot:
    proxies: list[ProxyEndpoint]
    health_history: dict[str, list[ProxyHealthEvent]]
    quarantined_until: dict[str, float]


class ProxyPoolStore(Protocol):
    def load(self) -> ProxyPoolSnapshot | None:
        ...

    def save(self, snapshot: ProxyPoolSnapshot) -> None:
        ...


class InMemoryProxyPoolStore:
    """Persistence adapter to carry proxy health state across allocator instances."""

    def __init__(self) -> None:
        self._snapshot: ProxyPoolSnapshot | None = None

    def load(self) -> ProxyPoolSnapshot | None:
        return self._snapshot

    def save(self, snapshot: ProxyPoolSnapshot) -> None:
        self._snapshot = snapshot


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

    def __init__(
        self,
        proxies: list[ProxyEndpoint],
        *,
        store: ProxyPoolStore | None = None,
        now_fn=time.time,
        region_weights: dict[str, float] | None = None,
        sticky_window_seconds: int = 300,
        quarantine_window_seconds: int = 180,
    ) -> None:
        if not proxies:
            raise ValueError("proxies must not be empty")

        self._store = store
        self._now = now_fn
        self._region_weights = region_weights or {}
        self._sticky_window_seconds = sticky_window_seconds
        self._quarantine_window_seconds = quarantine_window_seconds

        self._proxies_by_id = {proxy.endpoint_id: proxy for proxy in proxies}
        self._health_history: dict[str, list[ProxyHealthEvent]] = {}
        self._quarantined_until: dict[str, float] = {}
        self._sticky_proxy_by_session: dict[str, tuple[str, float]] = {}
        self._rotation_audit: list[RotationAuditEvent] = []

        if self._store is not None:
            snapshot = self._store.load()
            if snapshot is not None and snapshot.proxies:
                self._proxies_by_id = {proxy.endpoint_id: proxy for proxy in snapshot.proxies}
                self._health_history = {
                    key: list(events) for key, events in snapshot.health_history.items()
                }
                self._quarantined_until = dict(snapshot.quarantined_until)

        self._next_index = 0
        self._persist_pool()

    def allocate(
        self,
        session_id: str,
        behavior_profile_id: str,
        preferred_region: str | None = None,
    ) -> IdentityBundle:
        sticky = self._sticky_proxy_by_session.get(session_id)
        now = self._now()
        if sticky is not None:
            proxy_id, expires_at = sticky
            if expires_at >= now and not self.is_quarantined(proxy_id):
                proxy = self._proxies_by_id.get(proxy_id)
                if proxy is not None:
                    return self._build_bundle(proxy, session_id, behavior_profile_id)

        proxy = self._pick_best_proxy(preferred_region=preferred_region)
        self._sticky_proxy_by_session[session_id] = (proxy.endpoint_id, now + self._sticky_window_seconds)
        self._persist_pool()
        return self._build_bundle(proxy, session_id, behavior_profile_id)

    def rotate(
        self,
        current: IdentityBundle,
        session_id: str,
        behavior_profile_id: str,
        *,
        reason: RotationReason = RotationReason.MANUAL,
        risk_score: float | None = None,
    ) -> IdentityBundle:
        if reason in (RotationReason.RISK_THRESHOLD, RotationReason.PROXY_UNHEALTHY):
            self.quarantine_proxy(
                current.proxy.endpoint_id,
                duration_seconds=self._quarantine_window_seconds,
                reason=reason.value,
            )

        next_proxy = self._pick_best_proxy(
            preferred_region=current.proxy.region,
            exclude={current.proxy.endpoint_id},
        )
        if next_proxy.endpoint_id == current.proxy.endpoint_id:
            return current

        now = self._now()
        rotated = self._build_bundle(next_proxy, session_id, behavior_profile_id)
        self._sticky_proxy_by_session[session_id] = (next_proxy.endpoint_id, now + self._sticky_window_seconds)
        self._rotation_audit.append(
            RotationAuditEvent(
                session_id=session_id,
                from_proxy_id=current.proxy.endpoint_id,
                to_proxy_id=next_proxy.endpoint_id,
                reason_code=reason,
                timestamp=now,
                risk_score=risk_score,
            )
        )
        self._persist_pool()
        return rotated

    def record_proxy_health(
        self,
        endpoint_id: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        reason: str | None = None,
    ) -> ProxyEndpoint:
        proxy = self._proxies_by_id.get(endpoint_id)
        if proxy is None:
            raise KeyError(endpoint_id)

        event = ProxyHealthEvent(
            endpoint_id=endpoint_id,
            timestamp=self._now(),
            success=success,
            latency_ms=latency_ms,
            reason=reason,
        )
        history = self._health_history.setdefault(endpoint_id, [])
        history.append(event)
        if len(history) > 50:
            del history[:-50]

        target = 1.0 if success else 0.2
        if latency_ms is not None and success:
            target = max(0.0, target - min(max(latency_ms - 350.0, 0.0) / 1000.0, 0.3))

        smoothed = (0.75 * proxy.health_score) + (0.25 * target)
        updated_proxy = replace(proxy, health_score=_clamp01(smoothed))
        self._proxies_by_id[endpoint_id] = updated_proxy

        if not success and self._consecutive_failures(endpoint_id) >= 3:
            self.quarantine_proxy(endpoint_id, duration_seconds=self._quarantine_window_seconds, reason="consecutive_failures")

        self._persist_pool()
        return updated_proxy

    def get_proxy_health_history(self, endpoint_id: str) -> list[ProxyHealthEvent]:
        return list(self._health_history.get(endpoint_id, []))

    def quarantine_proxy(self, endpoint_id: str, *, duration_seconds: int, reason: str) -> None:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if endpoint_id not in self._proxies_by_id:
            raise KeyError(endpoint_id)

        self._quarantined_until[endpoint_id] = self._now() + duration_seconds
        self._persist_pool()

    def is_quarantined(self, endpoint_id: str) -> bool:
        self.unquarantine_expired()
        expires_at = self._quarantined_until.get(endpoint_id)
        if expires_at is None:
            return False
        return expires_at > self._now()

    def unquarantine_expired(self) -> int:
        now = self._now()
        expired = [endpoint_id for endpoint_id, expires_at in self._quarantined_until.items() if expires_at <= now]
        for endpoint_id in expired:
            self._quarantined_until.pop(endpoint_id, None)
        if expired:
            self._persist_pool()
        return len(expired)

    def rotation_audit_log(self) -> list[RotationAuditEvent]:
        return list(self._rotation_audit)

    def _build_bundle(self, proxy: ProxyEndpoint, session_id: str, behavior_profile_id: str) -> IdentityBundle:
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

    def _pick_best_proxy(
        self,
        *,
        preferred_region: str | None = None,
        exclude: set[str] | None = None,
    ) -> ProxyEndpoint:
        self.unquarantine_expired()
        blocked = exclude or set()

        candidates = [
            proxy
            for proxy in self._proxies_by_id.values()
            if proxy.endpoint_id not in blocked and not self.is_quarantined(proxy.endpoint_id)
        ]
        if not candidates:
            candidates = [proxy for proxy in self._proxies_by_id.values() if proxy.endpoint_id not in blocked]
        if not candidates:
            raise RuntimeError("no eligible proxies available")

        weighted = sorted(
            ((proxy, self._weight(proxy, preferred_region=preferred_region)) for proxy in candidates),
            key=lambda item: item[1],
            reverse=True,
        )

        top_weight = weighted[0][1]
        pool = [proxy for proxy, weight in weighted if weight >= top_weight * 0.85]
        pick = pool[self._next_index % len(pool)]
        self._next_index += 1
        return pick

    def _weight(self, proxy: ProxyEndpoint, *, preferred_region: str | None) -> float:
        history = self._health_history.get(proxy.endpoint_id, [])
        window = history[-10:]
        failures = len([event for event in window if not event.success])
        failure_rate = failures / len(window) if window else 0.0

        region_weight = self._region_weights.get(proxy.region, 1.0)
        if preferred_region and proxy.region == preferred_region:
            region_weight += 0.1

        failure_penalty = max(0.1, 1.0 - (0.75 * failure_rate))
        return proxy.health_score * region_weight * failure_penalty

    def _consecutive_failures(self, endpoint_id: str) -> int:
        history = self._health_history.get(endpoint_id, [])
        count = 0
        for event in reversed(history):
            if event.success:
                break
            count += 1
        return count

    def _persist_pool(self) -> None:
        if self._store is None:
            return

        self._store.save(
            ProxyPoolSnapshot(
                proxies=list(self._proxies_by_id.values()),
                health_history={key: list(events) for key, events in self._health_history.items()},
                quarantined_until=dict(self._quarantined_until),
            )
        )


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
