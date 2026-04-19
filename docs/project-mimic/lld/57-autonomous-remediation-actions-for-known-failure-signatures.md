# LLD 57: Autonomous Remediation Actions for Known Failure Signatures

## Feature

Strategic Improvements #50: Add autonomous remediation actions for known failure signatures.

## Scope

Introduce an autonomous remediation service that maps known failure signatures to deterministic remediation action plans and executes those plans when thresholds are breached.

- Add tenant-scoped remediation signature policies.
- Add threshold-based trigger evaluation with cooldown protections.
- Add autonomous action execution workflows for known action types.
- Record immutable execution history with per-action outcomes.
- Support in-memory and JSON-file persistence.
- Expose versioned and legacy API routes with RBAC, metering, and audit events.

This increment focuses on control-plane remediation orchestration and not direct Kubernetes operator integration.

## Data and Control Design

- Signature policy fields:
  - `signature_id`
  - `tenant_id`
  - `incident_class`
  - `failure_code` (optional)
  - `threshold`
  - `cooldown_seconds`
  - `enabled`
  - `action_plan[{action_type, parameters}]`
  - `last_triggered_at`
  - `created_at`
  - `updated_at`
- Trigger input fields:
  - `observed_value`
  - `signal_label`
  - `execute` (boolean)
  - `context` (optional structured details)
- Execution fields:
  - `execution_id`
  - `signature_id`
  - `tenant_id`
  - `observed_value`
  - `threshold`
  - `matched`
  - `executed`
  - `reason`
  - `initiated_by`
  - `signal_label`
  - `action_results[{action_type, success, status, details}]`
  - `created_at`

Known action handlers in this increment:

- `queue.requeue_expired_leases`
- `queue.replay_dead_letter`
- `control_plane.failover_execute`
- `feature_flag.disable`

## Workflow Design

1. Admin defines or updates remediation signature policy.
2. Operator submits observed failure signal for a signature.
3. Service evaluates threshold, enablement, and cooldown.
4. If matched and execution enabled, service executes configured action plan.
5. Service stores execution record and returns deterministic outcome payload.
6. Operators query execution history and status for incident visibility.

## Failure Policy

- Unknown signatures are rejected.
- Tenant scope mismatch is rejected.
- Invalid thresholds, cooldowns, or action plans are rejected.
- Unknown action types are captured as failed action results.
- Execution continues across action steps; one failed action does not erase prior successful actions.
- If trigger is below threshold or cooldown is active, execution is skipped with explicit reason.

## Rollout

1. Seed initial signatures for recurring failure classes.
2. Enable autonomous remediation in staging with dry-run (`execute=false`) checks.
3. Validate action handlers against queue and failover runbooks.
4. Enable execution mode for selected signatures.
5. Expand signature/action coverage as incident taxonomy evolves.
