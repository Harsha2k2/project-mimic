# LLD 36: Webhook/Event Subscriptions for Session Lifecycle Events

## Feature

Needed + Partial #29: Add webhook/event subscription system for lifecycle events.

## Scope

Add first-party event subscriptions so external systems can receive session lifecycle notifications via webhooks.

- Register webhook subscriptions by tenant.
- List registered subscriptions.
- Deliver lifecycle events to matching active subscriptions.
- Support memory and file-backed subscription stores.

This increment focuses on synchronous best-effort webhook delivery for core session lifecycle events.

## Event Contract

Envelope fields:

- `event_id`
- `event_type`
- `tenant_id`
- `timestamp`
- `payload`

Lifecycle event types in this increment:

- `session.create`
- `session.reset`
- `session.step`
- `session.rollback`
- `session.resume`

## Workflow Design

1. Operator creates subscriptions through API.
2. Session lifecycle handlers emit event envelopes.
3. Publisher filters subscriptions by tenant, active flag, and event filter.
4. Matching endpoints receive JSON webhook payloads.

## Failure Policy

- Delivery failures are isolated per subscription.
- API session flows continue even if webhook delivery fails.
- Invalid subscription configuration is rejected at creation time.

## Rollout

1. Enable admin-only subscription management endpoints.
2. Start with key lifecycle events and best-effort delivery.
3. Add retries and DLQ-backed delivery guarantees in later increments.