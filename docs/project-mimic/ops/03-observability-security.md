# Ops: Observability and Security

## 1) Observability Objectives

- Detect perception, grounding, and execution regressions quickly.
- Explain why any step succeeded or failed.
- Support deterministic replay for incident analysis.

## 2) Telemetry Design

Metrics (Prometheus):

- orchestrator
  - step latency p50/p95/p99
  - retry count by error class
  - state transition failure rates
- vision
  - AnalyzeFrame latency
  - VLM invocation ratio
  - grounding confidence distribution
- mimetic
  - plan generation latency
  - event emission drift
- browser workers
  - startup latency
  - crash/restart rate
  - action verification success

Logs (Loki):

- structured JSON logs with trace_id, session_id, step_id
- event categories: decision, inference, emit, verify, recover

Traces (OTel):

- end-to-end span from goal ingress to final completion
- child spans for capture, inference, grounding, emit, verify

## 3) SLOs and Alerts

Primary SLOs:

- action verification success rate >= 97%
- AnalyzeFrame p95 <= 700 ms
- orchestrator step p95 <= 150 ms
- browser startup p95 <= 8 s

Alert examples:

- grounding confidence median drop > 15% in 10 min
- challenge rate spike above baseline by 2x
- retry budget exhaustion above threshold

## 4) Security Controls

- mTLS for all gRPC traffic.
- workload identity and least-privilege service accounts.
- secrets stored in cloud secret manager with periodic rotation.
- network policies restricting east-west access.
- image signing and SBOM validation in CI.

## 5) Data Protection

- encrypt data in transit and at rest.
- redact sensitive fields in logs.
- scoped retention:
  - hot telemetry short retention
  - audit records longer retention per policy
- signed access logs for forensic traceability.

## 6) Incident Response

Runbook summary:

1. detect via SLO breach or anomaly alert
2. identify failing layer from traces and metrics
3. mitigate with traffic shaping, rollback, or policy switch
4. replay sampled sessions for root cause
5. apply fix and validate recovery gates

## 7) Validation Checklist

- All services expose health and readiness endpoints.
- Every mutating RPC carries idempotency key.
- Every step is replayable from artifact and event stream.
- Alerting and dashboards are version-controlled.
