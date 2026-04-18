# LLD 15: Persistent Session Metadata Store

## Feature

Needed + Missed #8: Add persistent metadata store for session records.

## Scope

This increment adds pluggable persistence for session metadata and wires a file-backed store in API runtime.

- Session metadata persistence abstraction.
- In-memory metadata store for tests.
- JSON file metadata store for local durability.
- Session registry writes metadata on lifecycle changes.

Full database-backed metadata (Postgres) and migrations are out-of-scope.

## Components

- `SessionMetadataStore` protocol in `session_lifecycle.py`
- `InMemorySessionMetadataStore`
- `JsonFileSessionMetadataStore`
- Optional API env wiring:
  - `SESSION_METADATA_STORE=file|memory`
  - `SESSION_METADATA_FILE_PATH=<path>`

## Data Model

Persisted metadata per session:

- `session_id`
- `tenant_id`
- `goal`
- `status`
- `created_at`
- `last_accessed_at`
- `expires_at`

## Registry Behavior

- Persist metadata on create/reset/step transitions/rollback/resume/failure/completion/scavenge.
- Load existing metadata for listing if in-memory records are empty (best-effort).

## Test Plan

1. File metadata store persists records across registry re-instantiation.
2. Session listing reads metadata from file store after restart-like reinit.
3. Existing session lifecycle tests remain green.

## Rollout

1. Start with file store in staging.
2. Move to DB-backed store in subsequent feature.
3. Add metadata retention and archival policies later.
