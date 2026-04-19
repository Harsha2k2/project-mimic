# LLD 35: Official Python and TypeScript SDKs for Client Integration

## Feature

Needed + Partial #28: Publish official SDKs (Python and TypeScript) for client integration.

## Scope

Introduce first-party client SDKs that wrap the most common control-plane operations with stable method interfaces.

- Python SDK package (`project_mimic_sdk`) for backend/service integration.
- TypeScript SDK package (`@project-mimic/sdk`) for frontend and Node integration.
- Shared method coverage for session lifecycle and operator snapshot workflows.

This increment focuses on baseline API coverage and packaging scaffolding, not exhaustive endpoint parity.

## Method Surface

Both SDKs support:

- Create session
- Step session
- Session state
- List sessions
- Restore session
- Rollback session
- Resume session
- Operator snapshot

## Workflow Design

1. Configure SDK client with base URL and optional auth/tenant context.
2. Build and send versioned API requests.
3. Parse JSON responses and return typed/object payloads.
4. Raise deterministic client errors for non-2xx responses.

## Failure Policy

- HTTP errors propagate as SDK-specific exceptions/errors with status and response details.
- Non-JSON or non-object responses are rejected.
- Network and timeout failures are surfaced as actionable client errors.

## Rollout

1. Publish Python SDK package from repository source tree.
2. Publish TypeScript SDK package from `sdk/typescript`.
3. Expand endpoint coverage and generated typing in follow-on increments.