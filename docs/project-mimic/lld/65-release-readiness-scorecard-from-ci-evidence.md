# LLD 65: Release Readiness Scorecard Auto-Generated from CI Evidence

## Feature

Strategic Improvements #58: Add release readiness scorecard auto-generated from CI evidence.

## Scope

Introduce a release readiness service that computes release scorecards from CI gate evidence.

- Generate release scorecards with weighted gate contributions.
- Represent blocked release conditions from critical and required gate failures.
- Persist scorecard history for release IDs and tenant visibility.
- Support in-memory and JSON-file persistence.
- Expose versioned and legacy APIs with RBAC, audit, usage metering, and realtime events.

This increment focuses on control-plane release gating intelligence, not CI execution orchestration.

## Data Model

- Scorecard:
  - `scorecard_id`
  - `tenant_id`
  - `release_id`
  - `generated_by`
  - `score`
  - `pass_ratio`
  - `minimum_pass_ratio`
  - `overall_status` (`ready`, `needs_review`, `blocked`)
  - `release_blocked`
  - `critical_failure_count`
  - `blocked_reasons[]`
  - `gate_results[]`
  - `created_at`, `updated_at`
- Gate result:
  - `gate_name`
  - `status` (`pass`, `fail`, `warn`)
  - `required`
  - `critical`
  - `weight`
  - `details`
  - `recorded_at`

## Scoring Policy

- Weighted pass ratio:
  - pass contributes full gate weight.
  - fail and warn contribute zero to pass ratio.
- Blocking rules:
  - Any failed critical gate blocks release.
  - Any failed required gate blocks release.
  - Pass ratio below configured minimum also blocks release.
- Overall status:
  - `blocked` when blocking rules trigger.
  - `ready` when not blocked and pass ratio is high.
  - `needs_review` when not blocked but pass ratio is below high-confidence threshold.

## Workflow

1. CI pipeline submits gate evidence and gate weights for a release candidate.
2. Service computes weighted readiness score and blocked reasons.
3. Service stores scorecard and emits readiness event for operator dashboards.
4. Operators list and fetch scorecards by release and status.

## Failure Policy

- Empty identifiers and missing evidence are rejected.
- Gate statuses must be one of `pass|fail|warn`.
- Gate weights must be positive.
- Tenant scoping applies to scorecard list/get operations.

## Rollout

1. Integrate CI jobs to post structured gate evidence.
2. Gate release promotions on scorecard block status.
3. Publish scorecards to operator/release dashboards.
4. Add release trend reporting in a follow-up increment.
