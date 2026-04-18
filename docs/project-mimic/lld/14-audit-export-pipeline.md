# LLD 14: Audit Export Pipeline (SIEM Destinations)

## Feature

Needed + Missed #7: Add audit export pipeline to SIEM destinations.

## Scope

This increment adds export sinks for audit events and an admin API endpoint to trigger exports.

- Sink abstraction (`AuditExportSink`).
- File sink (JSONL output).
- Webhook sink (HTTP POST JSON payload).
- Environment-driven sink bootstrap.
- Admin endpoint to export current audit events.

Batch scheduling, retries with DLQ, and managed SIEM connectors are out-of-scope.

## Components

- `src/project_mimic/audit_export.py`
  - `AuditExportSink` protocol
  - `FileAuditExportSink`
  - `WebhookAuditExportSink`
  - `build_audit_export_sink_from_env`
- API endpoint:
  - `POST /api/v1/audit/export`
  - `POST /audit/export` (legacy)

## Configuration

- `AUDIT_EXPORT_DESTINATION`: `file` or `webhook`
- `AUDIT_EXPORT_FILE_PATH`: path for file sink output
- `AUDIT_EXPORT_WEBHOOK_URL`: destination URL for webhook sink
- `AUDIT_EXPORT_WEBHOOK_TIMEOUT_SECONDS`: optional timeout

## Endpoint Behavior

- Requires `admin` role.
- Exports a snapshot of in-memory audit events.
- Returns count and sink metadata.

## Errors

- 400 if destination is not configured.
- 502 if sink export fails.

## Test Plan

1. File sink writes JSONL entries.
2. API export endpoint writes file and returns exported count.
3. Non-admin callers are denied export endpoint.

## Rollout

1. Start with file sink in staging.
2. Enable webhook sink for SIEM ingestion.
3. Add retry queue and delivery metrics in follow-up feature.
