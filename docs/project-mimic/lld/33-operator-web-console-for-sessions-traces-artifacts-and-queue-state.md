# LLD 33: Operator Web Console for Sessions, Traces, Artifacts, and Queue State

## Feature

Needed + Partial #26: Build operator web console for sessions, traces, artifacts, and queue state.

## Scope

Add a built-in operator dashboard to the API service that exposes the current runtime state in both HTML and JSON forms.

- Render a browser-friendly console page.
- Expose a JSON snapshot endpoint for tooling.
- Surface session listings, trace snapshots, artifact summaries, and queue state summaries.
- Allow the console to read optional file-backed snapshots when configured.

This increment does not introduce a standalone SPA or a separate frontend stack.

## Data Sources

- Sessions: `SessionRegistry.list_sessions()`
- Traces: `OpenTelemetryTracer.trace_snapshot()`
- Artifacts: optional JSON file path via `OPERATOR_CONSOLE_ARTIFACTS_FILE_PATH`
- Queue state: optional JSON file path via `OPERATOR_CONSOLE_QUEUE_FILE_PATH`

## Workflow Design

1. Collect live session and trace data from the API runtime.
2. Load optional artifacts and queue snapshots from configured files.
3. Render an HTML dashboard for operators.
4. Expose the same data through a JSON endpoint for automation.

## Failure Policy

- Missing optional files do not fail the console.
- Malformed optional snapshot files fail the console request with a structured 500 response.
- The console remains protected by API authentication.

## Rollout

1. Deploy the console behind admin-only access.
2. Use the JSON endpoint for scripts and the HTML page for manual triage.
3. Expand the artifacts and queue data contract if more persistence layers are added.
