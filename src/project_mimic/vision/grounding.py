"""Vision-to-DOM grounding helpers for action target selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    x: int
    y: int
    width: int
    height: int

    def area(self) -> int:
        return max(self.width, 0) * max(self.height, 0)

    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


@dataclass(frozen=True)
class UIEntity:
    entity_id: str
    label: str
    role: str
    text: str
    bbox: BBox
    confidence: float


@dataclass(frozen=True)
class DOMNode:
    dom_node_id: str
    role: str
    text: str
    bbox: BBox
    visible: bool
    enabled: bool
    z_index: int


@dataclass(frozen=True)
class GroundedTarget:
    entity_id: str
    dom_node_id: str
    x: int
    y: int
    score: float


def ground_entities_to_dom(
    entities: list[UIEntity],
    dom_nodes: list[DOMNode],
    top_k: int = 3,
) -> dict[str, list[GroundedTarget]]:
    """Ground UI entities to the best matching interactive DOM nodes."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    grounded: dict[str, list[GroundedTarget]] = {}
    for entity in entities:
        candidates: list[GroundedTarget] = []
        for node in dom_nodes:
            if not _is_interactable(node):
                continue

            score = _composite_score(entity, node)
            if score <= 0.0:
                continue

            cx, cy = node.bbox.center()
            candidates.append(
                GroundedTarget(
                    entity_id=entity.entity_id,
                    dom_node_id=node.dom_node_id,
                    x=cx,
                    y=cy,
                    score=score,
                )
            )

        grounded[entity.entity_id] = sorted(candidates, key=lambda c: c.score, reverse=True)[:top_k]

    return grounded


def _is_interactable(node: DOMNode) -> bool:
    return node.visible and node.enabled and node.bbox.area() > 0


def _composite_score(entity: UIEntity, node: DOMNode) -> float:
    overlap = _intersection_over_min_area(entity.bbox, node.bbox)
    role_match = 1.0 if _normalize(entity.role) == _normalize(node.role) else 0.0
    text_match = _token_match_ratio(entity.text, node.text)
    label_match = _token_match_ratio(entity.label, node.text)
    z_score = min(max(node.z_index / 100.0, 0.0), 1.0)

    return (
        (0.45 * overlap)
        + (0.20 * role_match)
        + (0.20 * text_match)
        + (0.10 * label_match)
        + (0.05 * z_score)
    ) * entity.confidence


def _normalize(value: str) -> str:
    return value.strip().lower()


def _token_match_ratio(left: str, right: str) -> float:
    left_tokens = {token for token in _normalize(left).split() if token}
    right_tokens = {token for token in _normalize(right).split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def _intersection_over_min_area(a: BBox, b: BBox) -> float:
    ax2 = a.x + a.width
    ay2 = a.y + a.height
    bx2 = b.x + b.width
    by2 = b.y + b.height

    inter_w = max(0, min(ax2, bx2) - max(a.x, b.x))
    inter_h = max(0, min(ay2, by2) - max(a.y, b.y))
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return 0.0

    min_area = min(a.area(), b.area())
    return inter_area / min_area if min_area else 0.0
