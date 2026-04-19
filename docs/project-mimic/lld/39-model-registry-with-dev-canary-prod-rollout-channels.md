# LLD 39: Model Registry with Dev/Canary/Prod Rollout Channels

## Feature

Needed + Partial #32: Add model registry with rollout channels (dev, canary, prod).

## Scope

Introduce a control-plane model registry that tracks model versions and channel assignments for staged rollouts.

- Register model versions with artifact URI and metadata.
- Promote a registered version into `dev`, `canary`, or `prod` channel.
- Query channel assignments and registered versions.
- Support memory and file-backed persistence.

This increment provides the registry control surface and channel mapping, not runtime inference routing.

## API Contract

- `POST /api/v1/models/registry/register`
- `GET /api/v1/models/registry/versions`
- `POST /api/v1/models/registry/channels/{channel}/promote`
- `GET /api/v1/models/registry/channels`

Legacy compatibility routes mirror under unversioned paths.

## Workflow Design

1. Register model version metadata.
2. Promote versions to rollout channels by policy.
3. Read channel assignments for deployment and release automation.

## Failure Policy

- Duplicate model/version registration fails.
- Promotion to unknown channel fails.
- Promotion of unregistered model/version fails.

## Rollout

1. Start with manual promotions in lower environments.
2. Integrate channel promotion gates into CI/CD.
3. Tie channel assignments to runtime traffic policies in follow-up increments.