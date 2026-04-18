"""Behavior profile presets used by mimetic planners."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JitterProfile:
    """Low-amplitude noise profile for human-like pointer movement."""

    name: str
    amplitude_px: float
    frequency_hz: float
    correction_probability: float


@dataclass(frozen=True)
class MovementProfile:
    """Movement timing and step configuration for viewport classes."""

    name: str
    step_count: int
    travel_ms: int
    dwell_ms: int
    jitter: JitterProfile


_DESKTOP_JITTER = JitterProfile(
    name="desktop",
    amplitude_px=1.2,
    frequency_hz=7.0,
    correction_probability=0.06,
)

_MOBILE_JITTER = JitterProfile(
    name="mobile",
    amplitude_px=2.2,
    frequency_hz=4.0,
    correction_probability=0.1,
)


def jitter_profile_for_device(device: str) -> JitterProfile:
    normalized = device.strip().lower()
    if normalized == "mobile":
        return _MOBILE_JITTER
    return _DESKTOP_JITTER


def movement_profile_for_viewport(viewport_width: int, viewport_height: int) -> MovementProfile:
    if viewport_width <= 0 or viewport_height <= 0:
        raise ValueError("viewport dimensions must be positive")

    area = viewport_width * viewport_height
    if viewport_width <= 480 or area <= 480 * 900:
        return MovementProfile(
            name="mobile-compact",
            step_count=16,
            travel_ms=760,
            dwell_ms=110,
            jitter=_MOBILE_JITTER,
        )

    if area >= 1900 * 1000:
        return MovementProfile(
            name="desktop-large",
            step_count=14,
            travel_ms=670,
            dwell_ms=85,
            jitter=_DESKTOP_JITTER,
        )

    return MovementProfile(
        name="desktop-standard",
        step_count=12,
        travel_ms=620,
        dwell_ms=80,
        jitter=_DESKTOP_JITTER,
    )
