# Diagram 1: End-to-End System Architecture

```mermaid
flowchart LR
    C[Client or API Caller] --> GI[Goal Ingress API]
    GI --> TP[Task Planner]
    TP --> DO[Decision Orchestrator]
    DO --> SA[Session Allocator]
    SA --> BW[Browser Worker]

    BW --> FC[Frame and DOM Capture]
    FC --> VG[Vision Gateway]
    VG --> TR[Triton Inference Server]
    TR --> AG[Action Grounder]
    AG --> DO

    DO --> ML[Mimetic Service Rust]
    ML --> BW

    BW --> TW[Target Websites]

    DO --> R[(Redis Session State)]
    DO --> P[(Postgres Jobs and Outcomes)]

    BW --> O[(S3 or GCS Artifacts)]
    BW --> K[(Kafka Telemetry)]
    DO --> K
    K --> CH[ClickHouse Analytics]
```

## What this shows

- Full control path from user goal to browser action.
- Vision feedback loop returning grounded targets.
- State, telemetry, and artifact persistence paths.
