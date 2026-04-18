# LLD: Visual-Spatial Brain

## 1) Purpose

Visual-Spatial Brain transforms pixels into executable actions using a Vision-to-Action loop with DOM grounding.

## 2) Pipeline Overview

1. Capture FrameBundle from browser worker.
2. Run detector and OCR for structural and textual signals.
3. Invoke VLM only for ambiguous intent or low confidence regions.
4. Build UIMap with entities, roles, text, and confidence.
5. Map visual entities to DOM candidates using spatial index.
6. Return grounded action candidate set to orchestrator.

## 3) Service Components

- FrameCaptureClient
- InferenceGateway
- UISegmenter (detector + OCR)
- SemanticResolver (local VLM)
- SpatialDOMMapper
- ActionGrounder
- ConfidenceCalibrator

## 4) Data Models

```python
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class UIEntity:
    entity_id: str
    label: str
    role: str
    polygon: List[Tuple[int, int]]
    text: str
    confidence: float

@dataclass
class GroundedTarget:
    dom_node_id: str
    x: int
    y: int
    score: float

@dataclass
class UIMap:
    entities: List[UIEntity]
    frame_hash: str
```

## 5) Grounding Strategy

- Build R-tree index of DOM bounding boxes from layout snapshot.
- For each visual entity:
  - Find intersecting and nearest interactive nodes.
  - Score candidates by semantic and spatial agreement.
  - Keep top K with confidence bounds.

Composite score:

score = wa * overlap + wb * role_match + wc * text_match + wd * interactability + we * history

## 6) Cascaded Inference for Scale

Tier 1 (default):

- lightweight detector + OCR on ROI/full frame.

Tier 2 (conditional):

- local VLM call for disambiguation.

Tier selection triggers:

- low confidence from Tier 1
- conflicting candidate labels
- repeated verification failures

## 7) Caching and Throughput Controls

- Perceptual frame hash deduplication.
- Temporal coherence cache for stable pages.
- ROI-first inference to reduce GPU load.
- Dynamic batching on Triton.

## 8) Verification Loop

After each action:

1. Capture post-action frame and DOM delta.
2. Validate expected state transition.
3. If not matched, downgrade confidence and route to recovery.

## 9) Failure Modes

- Occlusion and popovers hide actionable nodes.
- Dynamic content invalidates stale coordinates.
- Localization differences change text semantics.

Mitigations:

- z-index aware interactability checks
- rapid recapture on DOM mutation events
- multilingual OCR/VLM prompts per session locale

## 10) Test Plan

- Offline benchmark set with annotated UI entities.
- Grounding precision and recall by site family.
- End-to-end action success rate under layout drift.
