# Project Mimic Tech Stack

This file captures the concrete technologies selected for Stage 1.

## Core Stack by Layer

| Layer | Primary Tech | Why |
|---|---|---|
| Browser control | Playwright (Node.js) + Chromium | Stable automation API, strong CDP integration, mature ecosystem |
| Mimetic interaction | Rust microservice | Low latency event synthesis, memory safety, predictable performance |
| Decision orchestration | Python service | Fast iteration for planning and policy logic, strong ML tooling |
| Vision inference | NVIDIA Triton Inference Server | Dynamic batching, multi-model serving, GPU utilization |
| Vision models | Detector + OCR + local VLM (Phi-3-V/Llava class) | UI segmentation, text extraction, semantic reasoning |
| Inter-service RPC | gRPC + Protobuf | Typed contracts, low overhead, deadline propagation |
| Queue and stream | Kafka | Back-pressure handling and event pipeline durability |
| Session hot state | Redis | Low-latency state read/write for active sessions |
| Persistent state | Postgres | Job metadata, plans, outcomes, replay indexes |
| Artifact storage | S3 or GCS | Screenshots, traces, video artifacts |
| Metrics | Prometheus + Grafana | SLO tracking and autoscaling signals |
| Logs | Loki | Efficient structured logging at high cardinality |
| Cluster orchestration | Kubernetes + KEDA | Horizontal scaling driven by workload queues |
| Service security | mTLS (service mesh), secret manager | Encrypted internal traffic and short-lived credentials |

## Language Allocation

- Rust
  - Pointer trajectory generation
  - Keyboard cadence synthesis
  - Event emission timing
- Python
  - Decision Orchestrator
  - Behavior Tree and State Machine runtime
  - Policy engine and recovery strategies
- Node.js
  - Playwright browser worker runtime
  - CDP bridge to mimetic layer

## Cloud Targets

- AWS reference stack
  - EKS, MSK, ElastiCache, RDS, S3
- GCP reference stack
  - GKE, Pub/Sub or Kafka, Memorystore, Cloud SQL, GCS

## Non-Functional Targets (Stage 1)

- Session scale: 100k+ concurrent sessions (active + warm parked).
- Orchestrator p95 step decision latency: below 150 ms.
- Vision inference p95 for active step: below 400 ms with cascade.
- Browser worker startup p95: below 8 s with warmed image cache.
