"""Deterministic mimetic planners for pointer and keyboard event streams."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from .contracts import MimeticEvent, MimeticEventStream
from .profiles import movement_profile_for_viewport


@dataclass(frozen=True)
class TypoCorrectionStrategy:
    """Bounded strategy controlling typo and correction insertion frequency."""

    typo_probability: float = 0.04
    correction_probability: float = 0.95
    max_typos_per_text: int = 2

    def normalized(self) -> "TypoCorrectionStrategy":
        return TypoCorrectionStrategy(
            typo_probability=min(max(self.typo_probability, 0.0), 0.25),
            correction_probability=min(max(self.correction_probability, 0.0), 1.0),
            max_typos_per_text=max(self.max_typos_per_text, 0),
        )


def plan_pointer_stream(
    *,
    start_x: float,
    start_y: float,
    target_x: float,
    target_y: float,
    viewport_width: int,
    viewport_height: int,
    deterministic_seed: int | None = None,
) -> MimeticEventStream:
    profile = movement_profile_for_viewport(viewport_width, viewport_height)
    rng = Random(deterministic_seed)

    events: list[MimeticEvent] = []
    for index in range(profile.step_count):
        t = index / (profile.step_count - 1)
        eased = _ease_in_out_cubic(t)

        x = start_x + ((target_x - start_x) * eased)
        y = start_y + ((target_y - start_y) * eased)

        jitter_scale = 1.0 - abs((2.0 * t) - 1.0)
        jitter = profile.jitter.amplitude_px * jitter_scale
        x += rng.uniform(-jitter, jitter)
        y += rng.uniform(-jitter, jitter)

        x = min(max(x, 0.0), float(viewport_width - 1))
        y = min(max(y, 0.0), float(viewport_height - 1))

        event_time = int((profile.travel_ms * index) / (profile.step_count - 1))
        events.append(MimeticEvent(t_ms=event_time, x=x, y=y, event_type="move"))

    dwell = profile.dwell_ms
    events.append(MimeticEvent(t_ms=profile.travel_ms + dwell, x=target_x, y=target_y, event_type="down"))
    events.append(MimeticEvent(t_ms=profile.travel_ms + dwell + 35, x=target_x, y=target_y, event_type="up"))

    return MimeticEventStream(
        channel="pointer",
        profile=profile.name,
        deterministic_seed=deterministic_seed,
        events=events,
    )


def synthesize_typing_stream(
    text: str,
    *,
    base_delay_ms: int = 60,
    strategy: TypoCorrectionStrategy | None = None,
    deterministic_seed: int | None = None,
) -> MimeticEventStream:
    if base_delay_ms < 0:
        raise ValueError("base_delay_ms must be non-negative")

    normalized = (strategy or TypoCorrectionStrategy()).normalized()
    rng = Random(deterministic_seed)

    events: list[MimeticEvent] = []
    current_t = 0
    typo_count = 0

    for ch in text:
        should_typo = (
            ch.isalpha()
            and typo_count < normalized.max_typos_per_text
            and rng.random() < normalized.typo_probability
        )
        if should_typo:
            typo_char = _adjacent_typo(ch)
            current_t += _cadence_delay(typo_char, base_delay_ms)
            events.append(MimeticEvent(t_ms=current_t, key=typo_char, event_type="keydown"))
            current_t += 30
            events.append(MimeticEvent(t_ms=current_t, key=typo_char, event_type="keyup"))
            typo_count += 1

            if rng.random() <= normalized.correction_probability:
                current_t += 28
                events.append(MimeticEvent(t_ms=current_t, key="BACKSPACE", event_type="keydown"))
                current_t += 24
                events.append(MimeticEvent(t_ms=current_t, key="BACKSPACE", event_type="backspace"))
                current_t += 18
                events.append(MimeticEvent(t_ms=current_t, key="BACKSPACE", event_type="keyup"))

        current_t += _cadence_delay(ch, base_delay_ms)
        events.append(MimeticEvent(t_ms=current_t, key=ch, event_type="keydown"))
        current_t += 30
        events.append(MimeticEvent(t_ms=current_t, key=ch, event_type="keyup"))

    return MimeticEventStream(
        channel="keyboard",
        profile="typing-v1",
        deterministic_seed=deterministic_seed,
        events=events,
    )


def _ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - (((-2.0 * t) + 2.0) ** 3 / 2.0)


def _cadence_delay(ch: str, base_delay_ms: int) -> int:
    if ch.isspace():
        return base_delay_ms + 120
    if ch.isdigit():
        return base_delay_ms + 45
    if ch.isascii() and not ch.isalnum():
        return base_delay_ms + 65
    return base_delay_ms + 25


def _adjacent_typo(ch: str) -> str:
    if not ch.isalpha():
        return ch

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    lower = ch.lower()
    idx = alphabet.find(lower)
    if idx < 0:
        return ch

    replacement = alphabet[(idx + 1) % len(alphabet)]
    return replacement.upper() if ch.isupper() else replacement
