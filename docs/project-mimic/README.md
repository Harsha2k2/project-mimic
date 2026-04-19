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
  - `lld/14-audit-export-pipeline.md`
  - `lld/15-persistent-session-metadata-store.md`
  - `lld/16-durable-queue-backend.md`
  - `lld/17-idempotency-store-ttl-replay-protection.md`
  - `lld/18-request-size-and-timeout-guards.md`
  - `lld/19-hardened-cors-and-edge-security-policy-defaults.md`
  - `lld/20-ci-security-scans.md`
  - `lld/21-sbom-generation-and-ci-enforcement.md`
  - `lld/22-signed-container-images-and-verification-policy.md`
  - `lld/23-secret-rotation-automation-with-expiry-alarms.md`
  - `lld/24-disaster-recovery-backup-and-restore-automation.md`
  - `lld/25-canary-deployment-with-automatic-rollback-on-slo-breach.md`
  - `lld/26-deployment-pipeline-gates-for-helm-and-manifest-policy-checks.md`
  - `lld/27-end-to-end-tests-with-real-browser-workers-in-ci.md`
  - `lld/28-integration-lane-with-real-triton-gpu-inference-path.md`
  - `lld/29-load-and-stress-tests-with-capacity-thresholds-as-release-gates.md`
  - `lld/30-slo-burn-rate-alerts-wired-to-on-call-paging.md`
  - `lld/31-runbook-automation-for-common-incident-classes.md`
  - `lld/32-compliance-safe-data-deletion-workflows.md`
  - `lld/33-operator-web-console-for-sessions-traces-artifacts-and-queue-state.md`
  - `lld/34-cli-for-operational-workflows-restore-rollback-replay-quarantine.md`
  - `lld/35-official-python-and-typescript-sdks-for-client-integration.md`
  - `lld/36-webhook-event-subscriptions-for-session-lifecycle-events.md`
  - `lld/37-async-job-api-for-long-running-flows-submit-poll-cancel.md`
  - `lld/38-event-stream-delivery-via-sse-for-realtime-status.md`
  - `lld/39-model-registry-with-dev-canary-prod-rollout-channels.md`
  - `lld/40-online-model-and-grounding-drift-detection-with-threshold-alerts.md`
  - `lld/41-human-in-the-loop-review-queue-for-low-confidence-actions.md`
  - `lld/42-policy-decision-explorer-ui-with-explanation-trails.md`
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