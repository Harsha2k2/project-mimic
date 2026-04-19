# LLD 40: Online Model and Grounding Drift Detection with Threshold Alerts

## Feature

Needed + Partial #33: Add online model/grounding drift detection and threshold alerts.

## Scope

Add an online drift monitor that ingests metric samples, compares current behavior to baseline, and emits alert status when drift exceeds threshold.

- Ingest metric samples per stream and metric key.
- Build baseline from warm-up samples.
- Compute normalized drift score from recent window vs baseline.
- Expose status and active alerts through API.

This increment focuses on statistical drift signaling; it does not automate model rollback actions.

## API Contract

- `POST /api/v1/drift/samples`
- `GET /api/v1/drift/status`
- `GET /api/v1/drift/alerts`

Legacy routes mirror under unversioned paths.

## Workflow Design

1. Clients push model/grounding quality metrics to sample endpoint.
2. Monitor warms baseline and then evaluates recent-window drift.
3. Alert flag becomes active when drift score meets/exceeds threshold.
4. API exposes current status and active alerts for operations.

## Failure Policy

- Invalid sample payloads are rejected.
- Unknown metric status queries return 404.
- Alert evaluation is in-memory and best-effort for this increment.

## Rollout

1. Start with conservative thresholds.
2. Wire status checks into release and canary gates.
3. Integrate automated response policies in later increments.