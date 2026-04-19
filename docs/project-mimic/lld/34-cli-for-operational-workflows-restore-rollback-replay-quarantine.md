# LLD 34: CLI for Operational Workflows (Restore, Rollback, Replay, Quarantine)

## Feature

Needed + Partial #27: Build CLI for operational workflows (restore, rollback, replay, quarantine).

## Scope

Add an operator-focused CLI that executes high-value recovery and queue workflows without requiring ad hoc scripts.

- Restore a session checkpoint through the API.
- Roll back a session to its latest checkpoint through the API.
- Replay a dead-letter queue job from a persisted queue store file.
- Quarantine a queue job into dead-letter with a reason.

This increment introduces a single CLI entrypoint and does not replace existing API endpoints or CI workflows.

## Interface

Command: `project-mimic-ops`

Subcommands:

- `restore --session-id <id> --base-url <url> [--api-key <key>] [--tenant-id <tenant>]`
- `rollback --session-id <id> --base-url <url> [--api-key <key>] [--tenant-id <tenant>]`
- `replay --job-id <id> --queue-store <path>`
- `quarantine --job-id <id> --queue-store <path> [--reason <text>]`

## Workflow Design

1. Parse command and validate required arguments.
2. For restore and rollback, call the API endpoint and print JSON results.
3. For replay and quarantine, load the persisted queue snapshot and apply the runtime operation.
4. Persist updated queue state and print operation summary.

## Failure Policy

- API non-2xx responses fail the command with stderr details.
- Missing queue store file or unknown job ID fails with non-zero exit.
- Quarantine of completed jobs fails explicitly.

## Rollout

1. Publish CLI entrypoint in package scripts.
2. Use in operator runbooks for incident recovery and queue hygiene.
3. Extend with additional operational actions in later increments.