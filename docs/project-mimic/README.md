# Project Mimic Design Docs

This folder contains the end-to-end system design package for Project Mimic Stage 1 (High-Fidelity Simulation).

## Scope

- Build a distributed, vision-based browser execution engine.
- Replace selector-first automation with visual-spatial reasoning.
- Support large-scale concurrent execution (100k+ sessions) using Kubernetes.

## Documentation Map

- HLD
  - `hld/01-system-overview.md`
  - `hld/02-goal-to-click-dataflow.md`
- LLD
  - `lld/01-decision-orchestrator.md`
  - `lld/02-mimetic-interaction-layer.md`
  - `lld/03-visual-spatial-brain.md`
  - `lld/04-grpc-service-contracts.md`
  - `lld/05-model-migrations-and-errors.md`
  - `lld/06-orchestrator-internals.md`
  - `lld/07-vision-internals.md`
  - `lld/08-api-authentication-foundation.md`
  - `lld/09-api-authorization-rbac.md`
  - `lld/10-tenant-isolation-foundation.md`
  - `lld/11-tenant-rate-limit-and-quota.md`
  - `lld/12-api-key-lifecycle-management.md`
  - `lld/13-immutable-audit-logs.md`
- Ops and Scale
  - `ops/01-kubernetes-gpu-scaling.md`
  - `ops/02-proxy-fingerprinting-strategy.md`
  - `ops/03-observability-security.md`
  - `ops/04-contributor-quickstart.md`
  - `ops/05-troubleshooting.md`
  - `ops/06-production-readiness-checklist.md`
  - `ops/07-blue-green-rollout-runbook.md`
  - `ops/08-rollback-validation.md`
  - `ops/09-launch-review-template.md`
- ADR
  - `adr/README.md`
  - `adr/TEMPLATE.md`
- Stack
  - `TECH_STACK.md`
- Improvement Backlog
  - `../PROJECT_TODO_GAP_60.md`
- Architecture Diagrams (one-by-one)
  - `lld/06-orchestrator-internals.md`
  - `lld/07-vision-internals.md`
  - `diagrams/README.md`
  - `diagrams/01-system-architecture.md`
  - `diagrams/02-control-plane-architecture.md`
  - `diagrams/03-simulation-plane-architecture.md`
  - `ops/04-contributor-quickstart.md`
  - `ops/05-troubleshooting.md`
- ADR
  - `adr/README.md`
  - `adr/TEMPLATE.md`
  - `diagrams/04-goal-to-click-sequence.md`
  - `diagrams/05-decision-orchestrator-architecture.md`
  - `diagrams/06-kubernetes-deployment-architecture.md`
  - `diagrams/07-session-identity-proxy-architecture.md`

## Stage 1 Outcomes

- High-fidelity browser simulation with full web stack rendering.
- Vision-to-Action loop with coordinate and DOM grounding.
- Human-like mimetic interaction layer for pointer and keyboard synthesis.
- Hybrid Behavior Tree and State Machine decisioning for multi-step tasks.

## Constraints and Assumptions

- Performance-critical interaction components are implemented in Rust.
- High-level agent logic and orchestration are implemented in Python/Node.js.
- Internal services communicate through gRPC over mTLS.
- Cloud target is AWS or GCP with Kubernetes.

## Compliance Note

This design is intended for lawful automation, QA, and user emulation research in environments where you have authorization to operate.