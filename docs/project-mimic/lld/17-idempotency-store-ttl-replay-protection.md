# LLD 17: Persistent Idempotency Store with TTL and Replay Protection

## Feature

Needed + Missed #10: Add persistent idempotency key store with TTL and replay protection.

## Scope

This increment extends queue runtime idempotency handling with TTL and durable persistence.

- Idempotency entries include expiry timestamps.
- Queue dispatch blocks replay while key is unexpired.
- Expired idempotency keys are purged lazily.
- Idempotency expiry map is persisted in queue snapshot store.

Distributed/shared idempotency stores are out-of-scope.

## Design

### Data

- `_idempotency: dict[idempotency_key, job_id]`
- `_idempotency_expires: dict[idempotency_key, expires_at]`
- `idempotency_ttl_seconds` queue config (default 3600)

### Flow

1. `dispatch` checks and prunes expired idempotency entries.
2. If key exists and not expired, return existing job (replay-protected).
3. If key missing/expired, create new job and set fresh expiry.
4. Persist idempotency maps with queue state.

## Test Plan

1. Duplicate dispatch within TTL returns same job.
2. Dispatch after TTL creates a new job.
3. File-backed queue store preserves idempotency replay protection across reinit.

## Rollout

1. Start with conservative TTL.
2. Tune TTL by task profile.
3. Move to distributed idempotency backend in later scaling feature.
