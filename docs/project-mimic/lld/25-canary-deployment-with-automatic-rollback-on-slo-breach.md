# LLD 25: Canary Deployment with Automatic Rollback on SLO Breach

## Feature

Needed + Missed #18: Add canary deployment with automatic rollback on SLO breach.

## Scope

Add a canary deployment manifest and a workflow that evaluates SLO metrics, then rolls the canary back if the gate fails.

- Define a canary deployment alongside the stable control-plane deployment.
- Evaluate canary metrics from a JSON report.
- Automatically scale the canary deployment down when error rate or latency breach thresholds are exceeded.
- Emit a human-readable rollback summary for operators.

This increment focuses on the control plane canary path; worker canaries and service-mesh traffic shifting are out-of-scope.

## Metrics Contract

`artifacts/canary-slo.json` contains:

- `error_rate`
- `p95_latency_ms`
- `min_success_rate`
- `max_p95_latency_ms`
- `canary_namespace`
- `canary_deployment`

## Workflow Design

1. Load the SLO report.
2. Check the canary against the configured thresholds.
3. If healthy, leave the canary running and print a pass summary.
4. If breached, scale the canary deployment to zero replicas and print the rollback action.

## Failure Policy

- Missing or malformed report fails the gate.
- Breached thresholds trigger automatic rollback.
- Rollback failures fail the workflow.

## Rollout

1. Start with a low-traffic canary and strict thresholds.
2. Expand the report with additional SLO signals over time.
3. Integrate the same gate into release automation once stable.
