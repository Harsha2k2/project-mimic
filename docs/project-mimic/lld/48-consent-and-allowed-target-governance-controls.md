# LLD 48: Consent and Allowed-Target Governance Controls

## Feature

Needed + Partial #41: Add consent and allowed-target governance controls.

## Scope

Introduce tenant-governed controls that can require explicit consent and constrain actionable UI targets for high-risk interactions.

- Add tenant policy management for consent and target patterns.
- Add governance evaluation endpoint for operator diagnostics.
- Enforce governance checks on session step actions behind an environment toggle.
- Preserve legacy unversioned routes with deprecation headers.

This increment focuses on practical policy enforcement for interactive automation actions.

## Data and Control Design

- Governance policy fields per tenant:
  - `tenant_id`
  - `consent_required`
  - `allowed_target_patterns[]` (supports wildcard matching)
  - `created_at`
  - `updated_at`
- Evaluation inputs:
  - tenant scope
  - action type
  - target identifier
  - consent signal
- Consent signal sources during step enforcement:
  - `X-Consent-Granted` request header
  - `action.metadata.consent_granted`

## Workflow Design

1. Admin configures governance policy for a tenant.
2. Operator evaluates policy decisions via governance evaluate endpoint.
3. During session step execution, governance policy is evaluated before action execution.
4. When enforcement is enabled and a policy denies, the step is blocked with `403 FORBIDDEN`.
5. Allowed actions continue through normal session execution.

## Failure Policy

- Empty tenant IDs are rejected.
- Empty action type in evaluation is rejected.
- Missing policy yields `allowed=true` with reason `no_governance_policy`.
- If consent is required and not granted, reason is `consent_required`.
- If target patterns exist and target is missing/mismatched, request is denied.

## Rollout

1. Deploy policy endpoints and seed tenant policies.
2. Validate policies through evaluation endpoint in non-blocking mode.
3. Enable `GOVERNANCE_ENFORCEMENT_ENABLED=true` in staged environments.
4. Monitor deny rates and adjust target patterns and consent policy.
