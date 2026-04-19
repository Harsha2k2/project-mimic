# LLD 43: Feature Flag Service for Safe Progressive Rollout

## Feature

Needed + Partial #36: Add feature flag service for safe progressive rollout.

## Scope

Add a control-plane feature flag service with deterministic rollout evaluation and durable storage options.

- Create, update, list, fetch, and delete feature flags.
- Support percentage rollout for progressive enablement.
- Support tenant and subject allowlists for controlled exposure.
- Evaluate feature flag decisions deterministically using a stable hash bucket.
- Support memory and file-backed persistence.

This increment provides rollout safety primitives and API control; it does not yet wire flags into specific runtime execution branches.

## API Contract

- `POST /api/v1/feature-flags`
- `GET /api/v1/feature-flags`
- `GET /api/v1/feature-flags/{flag_key}`
- `DELETE /api/v1/feature-flags/{flag_key}`
- `POST /api/v1/feature-flags/evaluate`

Legacy routes mirror under unversioned paths.

## Data Model

Each feature flag stores:

- Identity: `flag_key`, `description`.
- Controls: `enabled`, `rollout_percentage`.
- Safety scopes: `tenant_allowlist`, `subject_allowlist`.
- Metadata and timestamps.

Evaluation output includes:

- Effective tenant and subject context.
- Match status, reason, and deterministic rollout bucket.
- Rollout percentage used for decision.

## Workflow Design

1. Admin defines or updates a feature flag rollout policy.
2. Operator submits evaluation request with subject context.
3. Service validates allowlists and computes deterministic bucket.
4. Service returns allow/deny outcome with explicit reason.

## Failure Policy

- Empty `flag_key` is rejected.
- Rollout percentage must be within 0-100.
- Unknown flags return 404.
- File store mode requires explicit file path configuration.

## Rollout

1. Start in memory mode in lower environments.
2. Enable file-backed mode for restart durability.
3. Integrate evaluations with deployment and execution controls in follow-up increments.
