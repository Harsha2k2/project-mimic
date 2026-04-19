# LLD 30: SLO Burn-Rate Alerts Wired to On-Call Paging

## Feature

Needed + Missed #23: Add SLO burn-rate alerts wired to on-call paging.

## Scope

Add a policy-driven burn-rate checker that evaluates service SLO burn rates and emits a paging payload when the threshold is exceeded.

- Read a repository policy file with alert thresholds and pager metadata.
- Evaluate the current burn-rate report.
- Fail the gate when burn-rate exceeds the warning or paging threshold.
- Emit an alert summary suitable for on-call paging or incident tooling.

This increment focuses on alert generation and policy enforcement rather than integrating a specific paging vendor.

## Policy Contract

`config/slo-alerts.yml` contains:

- `warning_burn_rate`
- `paging_burn_rate`
- `service_name`
- `on_call_target`

## Workflow Design

1. Load the alert policy.
2. Read the current burn-rate report.
3. Fail when warning or paging thresholds are exceeded.
4. Print an escalation summary for operators.

## Failure Policy

- Missing or malformed policy files fail the gate.
- Burn-rate beyond paging threshold fails the gate.
- A healthy report passes without escalation.

## Rollout

1. Start by reporting alerts without paging.
2. Integrate the output with the organization’s paging bridge.
3. Keep the policy version-controlled and reviewable.
