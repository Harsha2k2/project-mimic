# LLD: Decision Orchestrator

## 1) Module Purpose

Decision Orchestrator controls task execution from intent to verified UI action. It coordinates perception, grounding, action planning, execution, and recovery.

## 2) Design Pattern Choice

A hybrid model is used:

- Behavior Tree (BT)
  - Handles high-level multi-site strategy and fallback composition.
- Hierarchical State Machine (HSM)
  - Handles deterministic lifecycle of each atomic UI action.

Why hybrid:

- BT gives flexible control over long-running goals.
- HSM gives strict transitions, retries, and observability per step.

## 3) High-Level Behavior Tree

Root sequence:

1. InitializeContext
2. ParallelSiteSearch (5 branches, quorum mode)
3. NormalizeCandidates
4. ConstraintValidation
5. SelectBestOption
6. CommitResult

Site branch sequence:

1. OpenSite
2. EnterCriteria
3. SubmitSearch
4. ApplyLayoverConstraint
5. ExtractOffers
6. ValidateOfferQuality

## 4) Atomic Action State Machine

States:

1. Observe
2. Hypothesize
3. Ground
4. PlanMotion
5. Execute
6. Verify
7. Recover
8. Complete
9. Fail

State transition rules:

- Observe -> Hypothesize when fresh FrameBundle is available.
- Hypothesize -> Ground when intent confidence >= threshold.
- Ground -> PlanMotion when coordinate and DOM candidate agree.
- PlanMotion -> Execute after mimetic plan is generated.
- Execute -> Verify once events are acknowledged by browser worker.
- Verify -> Complete when expected state delta is confirmed.
- Verify -> Recover when no or wrong state change is observed.
- Recover -> Observe with alternate candidate or strategy shift.
- Recover -> Fail if retry budget is exhausted.

## 5) Core Interfaces

```python
from dataclasses import dataclass
from typing import List, Dict, Optional, Literal

Status = Literal["SUCCESS", "FAILURE", "RUNNING"]

@dataclass
class ActionIntent:
    name: str
    target_hint: str
    confidence: float

@dataclass
class GroundCandidate:
    dom_node_id: str
    x: int
    y: int
    confidence: float

@dataclass
class StepContext:
    session_id: str
    site_id: str
    intent: ActionIntent
    retry_count: int
    max_retries: int

class BehaviorNode:
    def tick(self, blackboard: Dict) -> Status:
        ...

class ActionStateMachine:
    def run(self, ctx: StepContext) -> Dict:
        ...
```

## 6) Blackboard Schema

- goal_context
  - objective, constraints, deadline, priorities.
- site_context
  - per-site status, challenge score, cookies, local cache keys.
- perception_context
  - latest UIMap, OCR tokens, frame hash, confidence map.
- action_context
  - intent, candidate list, selected target, execution ids.
- budget_context
  - retries left, time remaining, inference quota.

## 7) Target Selection Logic

Candidate score:

score = wv * vision_conf + ws * semantic_match + wi * interactability + wh * history_success

Where:

- vision_conf: confidence from detector/VLM.
- semantic_match: text/role alignment with intent.
- interactability: visible, enabled, not occluded.
- history_success: prior success for same template cluster.

## 8) Recovery Strategy

Error taxonomy:

- VisualAmbiguity
- DOMDesync
- NavigationTimeout
- FingerprintChallenge
- NetworkDegrade

Recovery policy examples:

- VisualAmbiguity
  - Increase ROI and invoke semantic disambiguation tier.
- DOMDesync
  - Refresh snapshot and invalidate stale nodes.
- FingerprintChallenge
  - Raise risk score and request identity rotation when threshold breached.

## 9) Flight Search Example

Goal: cheapest flight with around 1-hour layover across 5 sites.

Execution shape:

1. BT starts 5 site branches in parallel.
2. Each branch runs action HSM loop for filter and extraction.
3. Results are normalized to common schema.
4. Constraint validation removes offers outside layover bounds.
5. Lowest price among valid offers is selected.
6. Confidence and provenance are attached in final output.

## 10) Test Plan

- Unit tests
  - BT node status propagation.
  - State machine transition validity.
  - Retry budget and dead-end behavior.
- Integration tests
  - Grounding mismatch and alternate candidate recovery.
  - Multi-site parallel branch quorum behavior.
- Chaos tests
  - Delayed inference responses.
  - Browser worker restarts and checkpoint recovery.
