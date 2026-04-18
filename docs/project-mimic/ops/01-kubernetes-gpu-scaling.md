# Ops: Kubernetes and GPU Scaling Plan

## 1) Cluster Topology

Use separate node pools for distinct workload classes:

- cpu-browser pool
  - Browser Worker pods (Playwright + sidecars)
- gpu-inference pool
  - Triton + model runtime pods
- control-plane pool
  - Orchestrator, planner, APIs, policy services
- egress pool
  - Proxy gateway and outbound controls

## 2) Pod Composition

Browser Worker pod:

- container 1: Node.js Playwright runtime
- container 2: Rust Mimetic sidecar
- container 3: capture helper

Inference pod:

- Triton Inference Server
- model repository volume

## 3) Scaling Signals (KEDA)

Scale Browser Worker deployment by:

- pending session queue depth
- active step queue depth

Scale Inference deployment by:

- inference queue lag
- GPU utilization
- p95 AnalyzeFrame latency

Scale Orchestrator deployment by:

- NextStep RPC request rate
- CPU and memory pressure

## 4) Capacity Strategy for 100k Sessions

Do not assume all sessions are action-active at once.

Recommended model:

- active sessions: 10-20%
- warm parked sessions: 80-90%

This keeps GPU and browser CPU demand realistic while preserving concurrency semantics.

## 5) Scheduling and Isolation

- taints and tolerations for GPU workloads.
- topology spread constraints across zones.
- priority classes:
  - P0: active action sessions
  - P1: inference requests
  - P2: background refresh and warm-up
- per-tenant quotas and namespace isolation.

## 6) Rollout Strategy

1. Canary by site family.
2. Incremental traffic ramps with SLO guardrails.
3. Automatic rollback on threshold breaches.

SLO guardrails example:

- action success rate drop > 5%
- AnalyzeFrame p95 > 900 ms for 10 min
- Browser startup p95 > 12 s for 10 min

## 7) AWS and GCP Mapping

AWS:

- EKS
- MSK
- ElastiCache Redis
- RDS Postgres
- S3

GCP:

- GKE
- Kafka or Pub/Sub bridge
- Memorystore Redis
- Cloud SQL Postgres
- GCS

## 8) Cost Controls

- spot/preemptible nodes for non-critical parked sessions.
- model cascade to reduce VLM frequency.
- frame deduplication and ROI inference.
- aggressive image layer caching for browser worker startup.
