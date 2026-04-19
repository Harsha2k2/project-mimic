# LLD 32: Compliance-Safe Data Deletion Workflows

## Feature

Needed + Missed #25: Add compliance-safe data deletion workflows.

## Scope

Add a controlled deletion workflow for persisted session, queue, and audit artifacts.

- Delete session metadata records from file-backed stores.
- Remove matching queue snapshot entries from file-backed queue stores.
- Redact or delete matching audit export lines from file-backed export logs.
- Support dry-run and explicit confirmation modes.

This increment focuses on repository-managed deletion workflows, not on external legal hold or enterprise DLP systems.

## Configuration

`config/data-deletion.yml` contains:

- `session_metadata_file`
- `queue_snapshot_file`
- `audit_export_file`
- `session_ids`
- `tenant_id`
- `dry_run`

## Workflow Design

1. Load the deletion policy.
2. Identify affected records by session id and tenant.
3. Remove matching data from each configured file.
4. Emit a deletion report with before/after counts.

## Failure Policy

- Missing policy file fails the workflow.
- Missing target files fail the workflow unless dry-run is enabled.
- Malformed JSON or YAML fails the workflow.
- Dry-run never mutates files.

## Rollout

1. Start with dry-run in staging.
2. Require explicit operator confirmation for production deletion.
3. Expand the workflow as more persisted stores are introduced.
