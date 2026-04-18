# Diagram 5: Decision Orchestrator Architecture

## 5.1 Behavior Tree (Task Level)

```mermaid
flowchart TD
    ROOT[Root Sequence]
    I[Initialize Context]
    PS[Parallel Site Search x5]
    NC[Normalize Candidates]
    CV[Constraint Validation]
    SB[Select Best Option]
    CR[Commit Result]

    ROOT --> I --> PS --> NC --> CV --> SB --> CR

    subgraph SiteBranch[Per-Site Branch]
        OS[Open Site]
        EC[Enter Criteria]
        SS[Submit Search]
        LF[Apply Layover Filter]
        EO[Extract Offers]
        VO[Validate Offers]
        OS --> EC --> SS --> LF --> EO --> VO
    end

    PS --> SiteBranch
```

## 5.2 Action State Machine (Step Level)

```mermaid
stateDiagram-v2
    [*] --> Observe
    Observe --> Hypothesize: frame ready
    Hypothesize --> Ground: intent confidence OK
    Ground --> PlanMotion: target resolved
    PlanMotion --> Execute: path generated
    Execute --> Verify: events acknowledged

    Verify --> Complete: expected delta matched
    Verify --> Recover: mismatch or no change

    Recover --> Observe: fallback candidate
    Recover --> Fail: retry budget exhausted

    Complete --> [*]
    Fail --> [*]
```

## What this shows

- Hybrid BT plus HSM execution model.
- BT handles multi-site strategy.
- HSM handles deterministic action lifecycle.
