# LLD 51: Synthetic Monitoring for API, Queue, Worker, and Inference Paths

## Feature

Needed + Partial #44: Add synthetic monitoring for API, queue, worker, and inference paths.

## Scope

Add a synthetic monitoring capability that executes lightweight health probes across core runtime paths and exposes a consolidated monitoring report endpoint.

- Add synthetic monitor service with API, queue, worker, and inference probes.
- Add API endpoints for synthetic monitoring report retrieval (versioned and legacy).
- Gate synthetic monitoring by environment toggle.
- Capture synthetic monitoring success/failure in feature metrics.

This increment focuses on deterministic synthetic checks and visibility, not external alert routing.

## Data and Control Design

- Report structure:
  - `timestamp`
  - `overall_healthy`
  - `checks` map with `api`, `queue`, `worker`, `inference`
- Per-check fields:
  - `name`
  - `ok`
  - `latency_ms`
  - `message`
  - optional probe-specific fields (`queue_depth`, `dead_letter`, `entities`)
- API probe:
  - validates metrics snapshot path is healthy.
- Queue probe:
  - validates queue depth/dead-letter visibility and lease recovery call path.
- Worker probe:
  - validates orchestrator selection path execution.
- Inference probe:
  - validates Triton inference entity path when endpoint is configured.

## Workflow Design

1. Enable synthetic monitoring via environment toggle.
2. Configure optional Triton synthetic endpoint/model.
3. Request synthetic monitoring report through API.
4. Evaluate overall health and per-check details.
5. Track monitor result in feature metrics for trend analysis.

## Failure Policy

- When synthetic monitoring is disabled, endpoint returns not found.
- Unconfigured probes report `ok=false` with diagnostic message.
- Probe exceptions are captured per-check and do not crash report generation.
- Overall health is false when any required check fails.

## Rollout

1. Deploy with synthetic monitoring disabled by default.
2. Enable in test/staging environments with Triton endpoint configured.
3. Validate report consistency and role-based access.
4. Enable in production with dashboard/alert wiring in future increments.
