import json
from pathlib import Path

from project_mimic.vision.grounding import BBox, UIEntity
from project_mimic.vision.pipeline import (
    VisionTemporalCache,
    apply_role_thresholds,
    deduplicate_entities,
    normalize_ocr_text,
)


def _load_entities(path: str) -> list[UIEntity]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entities = []
    for item in payload["entities"]:
        entities.append(
            UIEntity(
                entity_id=item["entity_id"],
                label=item["label"],
                role=item["role"],
                text=item["text"],
                bbox=BBox(x=item["x"], y=item["y"], width=item["width"], height=item["height"]),
                confidence=item["confidence"],
            )
        )
    return entities


def test_deduplicate_entities_for_popover_overlap() -> None:
    entities = _load_entities("tests/fixtures/vision/popover_entities.json")
    deduped = deduplicate_entities(entities, overlap_threshold=0.8)
    assert len(deduped) == 1
    assert deduped[0].entity_id == "e1"


def test_ocr_normalization_for_locale_symbols() -> None:
    text = normalize_ocr_text("€ 120", locale="de_DE")
    assert text.startswith("EUR")


def test_role_thresholds_filter_low_confidence_overlay_links() -> None:
    entities = _load_entities("tests/fixtures/vision/overlay_entities.json")
    filtered = apply_role_thresholds(entities, thresholds={"textbox": 0.60, "link": 0.55})
    assert len(filtered) == 1
    assert filtered[0].entity_id == "e3"


def test_temporal_cache_key_and_storage() -> None:
    cache = VisionTemporalCache(max_entries=2, ttl_seconds=30)
    key = cache.make_key(b"frame-a")

    entities = _load_entities("tests/fixtures/vision/overlay_entities.json")
    cache.set(key, entities)

    cached = cache.get(key)
    assert cached is not None
    assert len(cached) == 2
