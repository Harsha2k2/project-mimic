# LLD 13: Immutable Audit Logs for Control Plane Mutations

## Feature

Needed + Missed #6: Add immutable audit logs for all control-plane mutations.

## Scope

This increment adds append-only in-memory audit logging for mutating API operations.

- Append-only audit event store in API runtime.
- Capture actor, tenant, request id, action, resource, and timestamp.
- Admin endpoint to query audit events with simple filters.

Durable storage, cryptographic signing, and SIEM export are out-of-scope for this increment.

## Event Model

Each audit event includes:

- `event_id`
- `timestamp`
- `request_id`
- `tenant_id`
- `api_key_id`
- `action`
- `resource_type`
- `resource_id`
- `details`

## Logged Mutations

- Session create/reset/step/rollback/resume.
- API key create/rotate/revoke.

## API Endpoints

- `GET /api/v1/audit/logs`
- `GET /audit/logs` (legacy)

Filters:

- `action`
- `tenant_id`
- `limit`

## Authorization

- Audit log read endpoints require `admin` role.

## Test Plan

1. Mutating session request creates an audit event.
2. Admin can query audit logs.
3. Non-admin cannot query audit logs.

## Rollout

1. Enable in staging to verify event shape and volume.
2. Add persistent store and export pipeline in next feature.
3. Add signed audit chain for tamper evidence in security hardening phase.
