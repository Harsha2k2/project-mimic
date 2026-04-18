"""Vision pipeline robustness helpers."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from .grounding import BBox, UIEntity


_SYMBOL_NORMALIZATION = {
    "en_US": {
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
    },
    "de_DE": {
        "€": "EUR",
    },
}


def normalize_ocr_text(text: str, locale: str = "en_US") -> str:
    normalized = text
    symbol_map = _SYMBOL_NORMALIZATION.get(locale, _SYMBOL_NORMALIZATION["en_US"])
    for symbol, replacement in symbol_map.items():
        normalized = normalized.replace(symbol, replacement)

    normalized = " ".join(normalized.split())
    return normalized.strip()


def deduplicate_entities(entities: list[UIEntity], overlap_threshold: float = 0.85) -> list[UIEntity]:
    kept: list[UIEntity] = []
    for candidate in sorted(entities, key=lambda item: item.confidence, reverse=True):
        if any(_overlap_ratio(candidate.bbox, existing.bbox) >= overlap_threshold for existing in kept):
            continue
        kept.append(candidate)
    return kept


def apply_role_thresholds(
    entities: list[UIEntity],
    thresholds: dict[str, float] | None = None,
) -> list[UIEntity]:
    thresholds = thresholds or {
        "button": 0.55,
        "textbox": 0.50,
        "link": 0.60,
    }
    out = []
    for entity in entities:
        threshold = thresholds.get(entity.role.lower(), 0.50)
        if entity.confidence >= threshold:
            out.append(entity)
    return out


@dataclass
class _CacheItem:
    entities: list[UIEntity]
    created_at: float


class VisionTemporalCache:
    def __init__(self, max_entries: int = 128, ttl_seconds: int = 30) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, _CacheItem] = {}

    def make_key(self, frame_bytes: bytes) -> str:
        return hashlib.sha256(frame_bytes).hexdigest()

    def get(self, key: str) -> list[UIEntity] | None:
        item = self._store.get(key)
        if item is None:
            return None

        if time.time() - item.created_at > self.ttl_seconds:
            self._store.pop(key, None)
            return None

        return item.entities

    def set(self, key: str, entities: list[UIEntity]) -> None:
        if len(self._store) >= self.max_entries:
            oldest_key = min(self._store.items(), key=lambda kv: kv[1].created_at)[0]
            self._store.pop(oldest_key, None)

        self._store[key] = _CacheItem(entities=entities, created_at=time.time())


def _overlap_ratio(a: BBox, b: BBox) -> float:
    ax2 = a.x + a.width
    ay2 = a.y + a.height
    bx2 = b.x + b.width
    by2 = b.y + b.height

    overlap_w = max(0, min(ax2, bx2) - max(a.x, b.x))
    overlap_h = max(0, min(ay2, by2) - max(a.y, b.y))
    overlap_area = overlap_w * overlap_h
    if overlap_area == 0:
        return 0.0

    min_area = min(max(a.width, 0) * max(a.height, 0), max(b.width, 0) * max(b.height, 0))
    return overlap_area / min_area if min_area else 0.0
