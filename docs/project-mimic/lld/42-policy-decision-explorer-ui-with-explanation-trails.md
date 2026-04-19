# LLD 42: Policy Decision Explorer UI with Explanation Trails

## Feature

Needed + Partial #35: Add policy decision explorer UI with explanation trails.

## Scope

Add a policy decision explorer that captures policy evaluations, exposes them through API endpoints, and renders an operator-facing UI for decision inspection.

- Evaluate policy decisions from explicit context inputs.
- Persist decision records with memory or file-backed storage.
- List and fetch policy decisions with tenant scoping.
- Render admin-only explorer UI that shows decision summaries and rule-by-rule explanation trails.

This increment focuses on observability and explainability of policy outcomes; it does not change downstream enforcement behavior in runtime middleware.

## API Contract

- `POST /api/v1/policy/decisions/evaluate`
- `GET /api/v1/policy/decisions`
- `GET /api/v1/policy/decisions/{decision_id}`
- `GET /api/v1/operator/policy`
- `GET /api/v1/operator/policy/snapshot`

Legacy routes mirror under unversioned paths.

## Data Model

Each policy decision record stores:

- Decision metadata: `decision_id`, `created_at`, `tenant_id`, `simulate`.
- Evaluation context: actor, site, action, jurisdiction, risk and authorization inputs.
- Outcome: `allowed`, `would_allow`, `reason`, `applied_rule_id`.
- Explanation trail: ordered per-rule verdict and reason entries.

## Workflow Design

1. Client submits policy context to evaluate endpoint.
2. Policy engine executes and emits ordered explanation entries.
3. Explorer persists the decision record and returns response payload.
4. Operators browse decision history and inspect explanation trail in UI.

## Failure Policy

- Invalid context returns 400.
- Unknown decision IDs return 404.
- Tenant mismatch hides records and returns 404 for detail lookup.
- File store mode requires explicit path configuration.

## Rollout

1. Enable API and UI with in-memory store by default.
2. Enable file store in environments that need restart durability.
3. Integrate explorer links into broader operator workflows in follow-up increments.
