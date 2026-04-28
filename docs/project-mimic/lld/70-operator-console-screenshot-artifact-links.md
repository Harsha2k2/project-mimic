# LLD 70: Operator Console Screenshot Artifact Links

## Feature

Expose live screenshot artifacts in the operator console with direct replay links to artifact content.

## Scope

- Summarize live screenshot artifacts from the in-memory artifact index.
- Render a dedicated screenshot artifact table in the HTML operator console.
- Surface replay URLs in the console table.
- Include live screenshot artifacts in the operator console JSON snapshot.

## Data Contract

`/api/v1/operator/snapshot` includes:

- `live_artifacts.available: bool`
- `live_artifacts.total: int`
- `live_artifacts.limit: int`
- `live_artifacts.items: list[dict]`

Each item contains:

- `artifact_id: str`
- `session_id: str`
- `artifact_type: str`
- `created_at: float`
- `size_bytes: int`
- `checksum_sha256: str`
- `metadata: dict[str, str]`
- `content_url: str`

## Rendering

- Add a new "Screenshot Artifacts" section to the operator console HTML.
- Each row links to `/api/v1/artifacts/{artifact_id}/content`.
- Show step index and trace id values when present in metadata.

## Failure Policy

- If no screenshot artifacts are available, render an empty state row.
- Missing optional artifact metadata does not fail the console.

## Test Plan

- Upload a screenshot artifact and verify the operator console HTML includes a replay link.
- Verify the operator snapshot includes the `live_artifacts` section.
