# LLD 37: Async Job API for Long-Running Flows (Submit, Poll, Cancel)

## Feature

Needed + Partial #30: Add async job API for long-running flows (submit, poll, cancel).

## Scope

Add a queue-backed API surface for long-running work so clients can submit jobs and monitor progress without blocking request-response workflows.

- Submit async jobs with idempotency keys.
- Poll job status and metadata.
- Cancel queued or leased jobs.
- Persist queue state when file-backed mode is enabled.

This increment introduces API control-plane contracts and queue-state transitions, not distributed worker execution.

## API Contract

- `POST /api/v1/jobs`: submit async job
- `GET /api/v1/jobs/{job_id}`: poll job status
- `POST /api/v1/jobs/{job_id}/cancel`: cancel job

Legacy compatibility routes are mirrored under unversioned paths.

## Workflow Design

1. Submit request dispatches job to queue runtime.
2. Job is returned with queued status.
3. Poll endpoint reads current queue state for the job.
4. Cancel endpoint transitions queued/leased jobs to canceled.

## Failure Policy

- Unknown job IDs return 404.
- Duplicate idempotency key returns existing job.
- Cancel on terminal jobs fails with 409.

## Rollout

1. Start with queue-backed API contracts and persistence hooks.
2. Integrate worker execution lanes in a follow-up increment.
3. Add event-stream updates for near-real-time status delivery.