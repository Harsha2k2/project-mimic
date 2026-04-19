# LLD 56: Predictive Autoscaling Based on Queue and Latency Trends

## Feature

Strategic Improvements #49: Add predictive autoscaling based on queue and latency trends.

## Scope

Introduce a predictive autoscaling service and API workflows that recommend replica adjustments using queue-depth and latency trend signals.

- Add tenant-scoped autoscaling policy definitions.
- Add signal ingestion for queue depth and latency samples.
- Add trend-aware recommendation engine with `scale_up`, `scale_down`, or `hold` decisions.
- Add recommendation safeguards: min/max replica bounds and cooldown windows.
- Add status visibility for recent means, trends, and last recommendation output.
- Add in-memory and JSON-file persistence backends.
- Expose versioned and legacy API routes with RBAC enforcement and deprecation headers.

This increment focuses on deterministic recommendation logic and does not directly mutate Kubernetes deployments.

## Data and Control Design

- Policy fields:
  - `policy_id`
  - `tenant_id`
  - `resource_type` (`model` or `worker`)
  - `resource_id`
  - `min_replicas`
  - `max_replicas`
  - `scale_up_step`
  - `scale_down_step`
  - `queue_depth_target`
  - `latency_ms_target`
  - `lookback_window`
  - `cooldown_seconds`
  - `last_recommendation_at`
  - `last_direction`
  - `last_desired_replicas`
  - `updated_at`
- Signal sample fields:
  - `queue_depth`
  - `latency_ms`
  - `observed_at`
- Recommendation output fields:
  - `direction`
  - `current_replicas`
  - `bounded_current_replicas`
  - `desired_replicas`
  - `queue_pressure`
  - `latency_pressure`
  - `queue_trend`
  - `latency_trend`
  - `confidence`
  - `reason`
  - `evaluated_at`

Trend and pressure logic:

- Recent means/trends are computed from the policy `lookback_window`.
- Pressure is computed as mean over target (`queue_recent_mean/queue_depth_target`, `latency_recent_mean/latency_ms_target`).
- Scale-up trigger: pressure above threshold with upward trend.
- Scale-down trigger: pressure below threshold with downward trend.
- Cooldown suppresses scale actions inside configured window.

## Workflow Design

1. Admin creates or updates predictive autoscaling policy per resource.
2. Operators ingest queue and latency samples as workload signals.
3. Operators request recommendation with current replica count.
4. Service evaluates trends/pressure and emits deterministic recommendation.
5. Operators query policy status for ongoing decision support.

## Failure Policy

- Empty identifiers and invalid resource type are rejected.
- Non-positive targets and invalid replica bounds are rejected.
- Signal ingestion for unknown policy is rejected.
- Tenant mismatch between caller and policy scope is rejected.
- Recommendation requests without signal history are rejected.

## Rollout

1. Enable predictive autoscaling API in staging with in-memory store.
2. Create baseline policies for critical model and worker pools.
3. Feed queue/latency samples from runtime telemetry adapters.
4. Validate recommendations against expected incident and low-load scenarios.
5. Enable file-backed persistence where policy continuity is required.
