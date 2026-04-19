# LLD 62: Partner Integration Templates and Managed Connectors

## Feature

Strategic Improvements #55: Add partner integration templates and managed connectors.

## Scope

Introduce reusable connector templates and tenant-managed connector instances for partner system integrations.

- Add integration template registry with provider, auth model, config contract, and default scopes.
- Add tenant connector instances referencing templates.
- Add connector update and health-check operations.
- Support in-memory and JSON-file persistence.
- Expose versioned and legacy API routes with RBAC, audit, metering, and realtime events.

This increment focuses on connector control-plane primitives, not live outbound call execution.

## Data and Control Design

- Template fields:
  - `template_id`
  - `provider`
  - `category`
  - `auth_type`
  - `required_config_keys[]`
  - `optional_config_keys[]`
  - `default_scopes[]`
  - `webhook_supported`
  - `rate_limit_per_minute`
  - `created_at`, `updated_at`
- Connector fields:
  - `connector_id`
  - `tenant_id`
  - `template_id`
  - `name`
  - `config{key->value}`
  - `enabled`
  - `health`
  - `last_checked_at`
  - `last_error`
  - `created_at`, `updated_at`
- Health check fields:
  - `connector_id`
  - `tenant_id`
  - `health`
  - `healthy`
  - `last_checked_at`
  - `last_error`

## Workflow Design

1. Admin defines/updates connector templates.
2. Operator creates tenant connector instance from template.
3. Operator updates connector config or enablement.
4. Operator runs health check to validate connector readiness.
5. API emits audit, metering, and realtime health events.

## Failure Policy

- Empty identifiers and invalid auth types are rejected.
- Template required config keys must be present on connector create/update.
- Duplicate connector IDs are rejected.
- Tenant mismatches return not found for instance operations.
- Health checks fail when connector is disabled or lacks config.

## Rollout

1. Seed templates for priority partner systems.
2. Create connectors per tenant in staging.
3. Validate health checks and connector lifecycle events.
4. Integrate runtime sync/execution in follow-up increments.
