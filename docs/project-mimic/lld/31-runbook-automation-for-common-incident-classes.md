# LLD 31: Runbook Automation for Common Incident Classes

## Feature

Needed + Missed #24: Add runbook automation for common incident classes.

## Scope

Add a small automation layer that turns common incident classes into structured runbook steps.

- Map incident classes to pre-written remediation plans.
- Emit a checklist, severity, and escalation target.
- Support manual dispatch in CI or local use.
- Keep the runbooks version-controlled with the rest of the repo.

This increment does not replace human incident response; it provides a consistent operator workflow.

## Incident Classes

- `api_session_conflict`
- `checkpoint_missing`
- `triton_inference_error`
- `identity_rotation_thrash`
- `flaky_ci`

## Workflow Design

1. Load the incident class.
2. Resolve the matching runbook.
3. Print a structured response containing steps, severity, and owner.
4. Exit non-zero for unknown incident classes.

## Failure Policy

- Unknown incident classes fail the workflow.
- Missing runbook definitions fail the workflow.
- Known incident classes always render the canonical remediation steps.

## Rollout

1. Start with the common incident classes already documented in troubleshooting.
2. Extend the mapping as new recurring incidents appear.
3. Reuse the output in chatops or paging automation later.
