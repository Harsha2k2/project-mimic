"""Vision modules for UI perception and action grounding."""

from .grounding import BBox, DOMNode, GroundedTarget, UIEntity, ground_entities_to_dom
from .pipeline import (
    VisionTemporalCache,
    apply_role_thresholds,
    deduplicate_entities,
    normalize_ocr_text,
)
from .triton_client import TritonConfig, TritonInferenceError, TritonVisionClient

__all__ = [
    "BBox",
    "DOMNode",
    "GroundedTarget",
    "VisionTemporalCache",
    "apply_role_thresholds",
    "deduplicate_entities",
    "normalize_ocr_text",
    "TritonConfig",
    "TritonInferenceError",
    "TritonVisionClient",
    "UIEntity",
    "ground_entities_to_dom",
]
