# LLD 38: Event Stream Delivery via SSE for Realtime Status

## Feature

Needed + Partial #31: Add event stream delivery (SSE or message bus) for realtime status.

## Scope

Add Server-Sent Events (SSE) delivery to expose near-realtime lifecycle and async-job status updates over HTTP.

- In-memory event broker with ordered event IDs.
- SSE endpoint for clients to stream events from a cursor (`after_id`).
- Tenant-aware event filtering.
- Event type filtering for focused subscriptions.

This increment implements SSE over HTTP and does not yet include external message bus fan-out.

## API Contract

- `GET /api/v1/events/stream`
  - Query: `after_id`, `max_events`, `wait_seconds`, `event_type`
  - Response: `text/event-stream`

Legacy endpoint mirrors under `/events/stream` with deprecation headers.

## Workflow Design

1. Runtime publishes lifecycle and async-job events to broker.
2. Stream endpoint reads events after requested cursor.
3. If none are available, endpoint waits briefly for new events.
4. Endpoint emits SSE frames with event metadata and payload.

## Failure Policy

- Stream endpoint returns keepalive frame when no events arrive before timeout.
- Publish failures are isolated and do not fail business APIs.
- Event backlog is bounded in memory by max event retention.

## Rollout

1. Start with in-memory broker and SSE contract.
2. Add replay persistence and external bus adapters in follow-up increments.
3. Integrate client SDK helper methods for stream consumption.