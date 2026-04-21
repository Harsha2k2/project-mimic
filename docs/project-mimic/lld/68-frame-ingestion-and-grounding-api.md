# LLD 68: Frame Ingestion and Grounding API

## Feature

Add an HTTP API that ingests a browser frame payload (screenshot + DOM snapshot), normalizes entities/nodes, and optionally produces a grounded click decision.

This increment closes an important gap between the current session API and the eventual live browser worker path by introducing a concrete frame contract for runtime integration.

## Scope

- Add `POST /api/v1/vision/analyze-frame` endpoint.
- Accept base64-encoded screenshot bytes and DOM snapshot payload.
- Normalize entity and DOM-node shapes into strict API payload contracts.
- Optionally infer entities from Triton when snapshot entities are missing.
- Return frame hash, parsed entities/dom nodes, and optional grounded click decision.
- Add legacy compatibility endpoint: `POST /vision/analyze-frame`.
- Add test coverage for endpoint behavior and API/gRPC parity.

## Contract Design

### Request

`AnalyzeFrameRequest`

- `screenshot_base64: str` (required)
- `dom_snapshot: dict[str, Any]` (optional, default `{}`)
- `task_hint: str` (optional)
- `infer_entities: bool` (optional, default `true`)

### Response

`AnalyzeFrameResponse`

- `frame_hash: str` (sha256 of decoded screenshot bytes)
- `entity_source: str` (`dom_snapshot`, `triton`, or `none`)
- `entities: list[UIEntityPayload]`
- `dom_nodes: list[DOMNodePayload]`
- `decision: DecideResponse | None`

## Processing Flow

1. Decode `screenshot_base64` using strict base64 validation.
2. Compute `frame_hash` from screenshot bytes.
3. Parse entities and dom nodes from `dom_snapshot`.
4. Normalize to strict payload contracts:
   - Support `bbox` object format.
   - Support flat `{x,y,width,height}` fallback format.
   - Clamp confidence to `[0.0, 1.0]`.
5. If no entities are available and `infer_entities=true`, call Triton inference client (if configured).
6. If both entities and dom nodes are present, call existing decision engine grounding path.
7. Return normalized payload and optional decision.

## Failure Policy

- Invalid base64 payload returns validation error (422).
- Empty decoded screenshot returns validation error (422).
- Triton inference failures return dependency failure (502) when inference is attempted.
- Missing entities/dom nodes does not fail request; `decision` is returned as `null`.

## Observability

- Record feature metric: `vision.analyze_frame`.
- Mark metric success when grounded decision status is `ok`.
- Reuse request trace IDs via API middleware.

## Compatibility

- New versioned endpoint: `/api/v1/vision/analyze-frame`.
- Deprecated compatibility endpoint: `/vision/analyze-frame` with deprecation headers.
- Reuses existing `DecideResponse` contract for grounded action output.

## Test Plan

- API test: valid frame + snapshot yields hash, `entity_source=dom_snapshot`, and grounded decision.
- API test: no entities and inference disabled yields `entity_source=none` and no decision.
- API test: invalid base64 rejected with validation error.
- API/gRPC parity test: `frame_hash` and entity count parity with `VisionServiceHandler.AnalyzeFrame`.

## Rollout

1. Land endpoint + models + normalization helpers.
2. Land API tests and API/gRPC parity test.
3. Wire browser worker runtime to publish real screenshots/dom snapshots to this endpoint in follow-up increment.
4. Extend operator artifacts to include per-frame payload/grounding traces in next increment.
