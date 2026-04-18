"""Vision modules for UI perception and action grounding."""

from .grounding import BBox, DOMNode, GroundedTarget, UIEntity, ground_entities_to_dom
from .triton_client import TritonConfig, TritonInferenceError, TritonVisionClient

__all__ = [
    "BBox",
    "DOMNode",
    "GroundedTarget",
    "TritonConfig",
    "TritonInferenceError",
    "TritonVisionClient",
    "UIEntity",
    "ground_entities_to_dom",
]
