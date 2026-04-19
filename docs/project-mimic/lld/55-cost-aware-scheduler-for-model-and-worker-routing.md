# LLD 55: Cost-Aware Scheduler for Model and Worker Routing

## Feature

Strategic Improvements #48: Add cost-aware scheduler for model and worker routing.

## Scope

Introduce a cost-aware scheduler service and API surface for selecting model and worker candidates based on routing objective.

- Add model profile registry with cost, latency, queue-depth, and quality signals.
- Add worker profile registry with cost, latency, queue-depth, and reliability signals.
- Add routing decisions for objectives: `balanced`, `min_cost`, and `low_latency`.
- Add objective-aware scoring that normalizes heterogeneous signals before weighting.
- Support in-memory and JSON-file persistence backends.
- Expose versioned and legacy API routes with RBAC and deprecation headers.

This increment defines deterministic control-plane routing decisions and not runtime autoscaling orchestration.

## Data and Control Design

- Model profile fields:
  - `candidate_id`
  - `model_id`
  - `region`
  - `cost_per_1k_tokens`
  - `latency_ms`
  - `queue_depth`
  - `quality_score`
  - `updated_at`
- Worker profile fields:
  - `candidate_id`
  - `worker_pool`
  - `region`
  - `cost_per_minute`
  - `latency_ms`
  - `queue_depth`
  - `reliability_score`
  - `updated_at`
- Routing decision fields:
  - `tenant_id`
  - `route_type`
  - `objective`
  - `selected_candidate`
  - `selected_resource`
  - `region`
  - `score`
  - `routed_at`
  - `rationale`

Signal normalization in scoring:

- Cost is normalized by a `10.0` divisor.
- Latency is normalized from ms to seconds.
- Queue depth is normalized by a `100.0` divisor.
- Quality/reliability is represented as a penalty using `1 - score`.

Objective weights:

- `min_cost`: strong bias toward normalized cost.
- `low_latency`: strong bias toward normalized latency.
- `balanced`: mixed weighting across normalized cost, latency, and queue pressure.

## Workflow Design

1. Admin upserts model and worker candidate profiles.
2. Operators list current candidates for observability.
3. Operator submits route decision request with objective.
4. Scheduler computes deterministic score per candidate and picks lowest score.
5. API returns selected target plus rationale and records metering/audit events.

## Failure Policy

- Empty candidate identifier, model/worker metadata, or region are rejected.
- Negative cost/latency/queue values are rejected.
- Quality/reliability scores outside `[0.0, 1.0]` are rejected.
- Unknown routing objectives are rejected.
- Scheduling requests fail when no profiles are available.
- Tenant override attempts are rejected when API key tenant scope is enforced.

## Rollout

1. Deploy scheduler service with in-memory store in staging.
2. Seed initial model/worker profiles from known pools.
3. Validate `min_cost` and `low_latency` route behavior through API tests.
4. Enable file-backed store for persistence where needed.
5. Monitor metering dimensions for route volume and tune weights as needed.
