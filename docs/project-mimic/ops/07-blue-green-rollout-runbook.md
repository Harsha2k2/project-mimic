# Blue-Green Rollout Runbook

## Scope

Covers rollout for API control plane and browser workers.

## Preconditions

- New image tags are built and scanned.
- Staging validation is complete.
- Production readiness checklist is fully green.

## Steps

1. Deploy Green stack in production namespace with no live traffic.
2. Run smoke tests against Green API and worker queue paths.
3. Mirror a low-risk traffic slice to Green and validate metrics.
4. Shift read traffic to Green (10% -> 50% -> 100%).
5. Shift write/mutating traffic to Green after stable latency and error rates.
6. Keep Blue online for rollback window.

## Validation Signals

- p95/p99 API latency within SLO envelope.
- Worker failure and retry rates stable.
- Triton queue depth and GPU utilization healthy.

## Exit Criteria

- Traffic fully shifted to Green.
- Blue remains idle but ready for rollback.
