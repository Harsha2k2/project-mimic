# Diagram 4: Goal to Coordinate Click Sequence

```mermaid
sequenceDiagram
    autonumber
    participant U as User Client
    participant G as Goal Ingress
    participant P as Task Planner
    participant O as Decision Orchestrator
    participant W as Browser Worker
    participant V as Vision Gateway
    participant T as Triton
    participant M as Mimetic Service

    U->>G: Submit goal and constraints
    G->>P: Build execution graph
    P->>O: Return planned tasks and budgets
    O->>W: Open target site task
    W-->>O: Return screenshot plus DOM snapshot
    O->>V: AnalyzeFrame(frame, dom)
    V->>T: Run detector and OCR
    T-->>V: UI entities and text
    V->>T: Optional VLM disambiguation
    T-->>V: Semantic labels
    V-->>O: Grounded action candidates
    O->>M: Plan pointer and keystrokes
    M-->>O: Event plans
    O->>W: Execute input events
    W-->>O: Post-action state and diff
    O->>O: Verify expected outcome
```

## What this shows

- Full Vision-to-Action loop with feedback verification.
- Conditional VLM invocation for ambiguous cases.
- Separation between planning and low-level input emission.
