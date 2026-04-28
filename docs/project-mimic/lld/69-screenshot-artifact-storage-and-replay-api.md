# LLD 69: Screenshot Artifact Storage and Replay API

## Feature

Persist screenshot artifacts uploaded by the runtime and expose list + replay endpoints so operators can inspect step-by-step frames.

## Scope

- Add screenshot artifact ingest endpoint for sessions.
- Add session artifact list endpoint with optional type filter.
- Add artifact content replay endpoint.
- Support in-memory or filesystem storage backends.
- Capture metadata such as step index, trace id, and storage backend.

## Contract Design

### Request

`POST /api/v1/sessions/{session_id}/artifacts/screenshot`

`ScreenshotArtifactIngestRequest`

- `screenshot_base64: str` (required)
- `expected_checksum_sha256: str | None` (optional)
- `step_index: int | None` (optional)
- `trace_id: str | None` (optional)
- `metadata: dict[str, str]` (optional)

### Response

`ArtifactRecordResponse`

- `artifact_id: str`
- `session_id: str`
- `artifact_type: str`
- `path: str`
- `checksum_sha256: str`
- `size_bytes: int`
- `created_at: float`
- `metadata: dict[str, str]`

### List

`GET /api/v1/sessions/{session_id}/artifacts?artifact_type=screenshot`

`ArtifactListResponse`

- `items: list[ArtifactRecordResponse]`
- `total: int`

### Content

`GET /api/v1/artifacts/{artifact_id}/content`

`ArtifactContentResponse`

- `artifact: ArtifactRecordResponse`
- `content_base64: str`

## Processing Flow

1. Validate session access and availability.
2. Decode `screenshot_base64` with strict base64 validation.
3. If `expected_checksum_sha256` is provided, verify it matches the decoded bytes.
4. Persist via `ArtifactManager` (memory or filesystem writer).
5. Return the recorded artifact metadata.

## Failure Policy

- Invalid base64 payload returns validation error (422).
- Checksum mismatch returns validation error (422).
- Unknown session returns not found (404).
- Invalid artifact type filter returns bad request (400).
- Unknown artifact id returns not found (404).

## Observability

- Emit audit event: `artifact.screenshot.upload`.
- Reuse API request correlation ids via middleware.

## Configuration

- `ARTIFACT_STORE`: `memory` (default) or `file`.
- `ARTIFACT_STORE_DIR`: required when `ARTIFACT_STORE=file`.

## Test Plan

- Upload screenshot artifact and verify list results include it.
- Retrieve artifact content and confirm byte-for-byte roundtrip.
- Validate checksum mismatch handling returns 422.
- Validate missing session returns 404.
