# LLD 41: Human-in-the-Loop Review Queue for Low-Confidence Actions

## Feature

Needed + Partial #34: Add human-in-the-loop review queue for low-confidence actions.

## Scope

Add a review queue where low-confidence action proposals can be submitted for manual approval/rejection.

- Queue low-confidence items with reason and confidence score.
- List pending and resolved review items.
- Resolve review items as approved or rejected with reviewer note.
- Support memory and file-backed queue persistence.

This increment provides control-plane queue management and auditability, not downstream automated execution.

## API Contract

- `POST /api/v1/reviews/queue`
- `GET /api/v1/reviews/queue`
- `POST /api/v1/reviews/queue/{review_id}/resolve`

Legacy routes mirror under unversioned paths.

## Workflow Design

1. Low-confidence candidate action is submitted to queue.
2. Reviewer fetches pending queue and picks an item.
3. Reviewer resolves item with approve/reject decision and note.
4. Queue item state updates and becomes available for audit/reporting.

## Failure Policy

- Unknown review IDs return 404.
- Invalid decisions are rejected.
- Re-resolving terminal review items fails with conflict.

## Rollout

1. Start with operator-facing review queue API.
2. Add UI workflow and reviewer assignment in follow-up increments.
3. Integrate resolution outcomes into policy and automation pipelines.