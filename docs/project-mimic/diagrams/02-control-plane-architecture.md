# Diagram 2: Control Plane Architecture

```mermaid
flowchart TB
    subgraph API[API Layer]
        GI[Goal Ingress API]
        PA[Policy and Compliance API]
    end

    subgraph CP[Control Plane Services]
        TP[Task Planner]
        DO[Decision Orchestrator]
        SE[Strategy Engine]
        RE[Recovery Engine]
        SA[Session Allocator]
    end

    subgraph STORE[Control Plane State]
        R[(Redis Blackboard)]
        P[(Postgres Metadata)]
    end

    subgraph OBS[Telemetry]
        K[(Kafka)]
        PR[Prometheus]
        LO[Loki]
    end

    GI --> TP
    TP --> DO
    PA --> DO
    DO --> SE
    DO --> RE
    DO --> SA

    DO --> R
    TP --> P
    SA --> P

    DO --> K
    TP --> K
    SA --> K

    DO --> PR
    DO --> LO
```

## What this shows

- Planning, orchestration, strategy, and recovery modules.
- Control state split between Redis and Postgres.
- Observability and event streaming integration.
