# LLD 16: Durable Queue Backend for Worker Jobs

## Feature

Needed + Missed #9: Add durable queue backend for worker jobs.

## Scope

This increment adds a file-backed durable queue store and wires it into queue runtime.

- Queue store abstraction for job payload persistence.
- In-memory durable store for tests.
- JSON file durable store for local crash recovery simulation.
- Queue operations persist pending/in-progress/dead-letter jobs.

Distributed queue backends (Redis streams/Kafka/RabbitMQ) are out-of-scope in this increment.

## Components

- `QueueStore` protocol in `queue_runtime.py`
- `InMemoryQueueStore`
- `JsonFileQueueStore`
- `InMemoryActionQueue` updated to persist state transitions

## Data Model

Persisted keys:

- `pending`: list of job dicts
- `in_progress`: map of job_id to leased job dict
- `dead_letter`: list of job dicts
- `processed_keys`: list of idempotency keys

## Runtime Behavior

- Queue loads persisted snapshot on startup.
- Every mutating operation writes snapshot to store.
- Replay/dead-letter behavior unchanged but durable.

## Test Plan

1. Enqueue jobs with file store and re-instantiate queue -> pending jobs restored.
2. Lease + dead-letter transitions persist across re-instantiation.
3. Existing queue tests stay green.

## Rollout

1. Enable file store in local/staging for validation.
2. Upgrade to distributed queue adapter in next increment.
3. Add queue consistency checks and compaction in follow-up.
