# LLD 61: Enterprise SSO (OIDC/SAML) and SCIM Provisioning

## Feature

Strategic Improvements #54: Add enterprise SSO (OIDC/SAML) and SCIM provisioning.

## Scope

Introduce enterprise identity federation capabilities with provider configuration, SCIM directory sync primitives, and authenticated identity resolution.

- Add tenant-scoped IdP provider management supporting `oidc` and `saml`.
- Add SCIM user upsert/list APIs for directory-provisioned identities.
- Add SCIM group upsert/list APIs for membership synchronization.
- Add identity authentication endpoint that resolves role from provider defaults plus SCIM user mapping.
- Support in-memory and JSON-file persistence backends.
- Expose versioned and legacy API routes with RBAC, audit, usage metering, and realtime event hooks.

This increment focuses on control-plane identity integration primitives and not full OAuth/SAML redirect flows.

## Data and Control Design

- Provider fields:
  - `tenant_id`
  - `provider_id`
  - `protocol` (`oidc`, `saml`)
  - `issuer`
  - `client_id`
  - optional protocol metadata endpoints
  - `enabled`
  - `default_role`
  - `created_at`, `updated_at`
- SCIM user fields:
  - `user_id`
  - `tenant_id`
  - `external_id`
  - `email`
  - `display_name`
  - `active`
  - `role`
  - `created_at`, `updated_at`
- SCIM group fields:
  - `group_id`
  - `tenant_id`
  - `external_id`
  - `display_name`
  - `members[]`
  - `created_at`, `updated_at`
- Authentication result fields:
  - `tenant_id`
  - `provider_id`
  - `subject`
  - `email`
  - `groups[]`
  - `role`
  - `scim_user_id`
  - `authenticated`
  - `authenticated_at`

## Workflow Design

1. Admin upserts tenant identity provider config.
2. Operator syncs SCIM users and groups from enterprise directory.
3. Operator calls authentication endpoint with provider + identity claims.
4. Service validates provider availability and resolves role via SCIM user mapping (fallback to provider default).
5. API emits usage and realtime authentication success signals.

## Failure Policy

- Empty tenant/provider identifiers are rejected.
- Unsupported protocol values are rejected.
- OIDC providers require authorize/token endpoints.
- SAML providers require SSO URL and entity ID.
- Invalid emails and roles in SCIM records are rejected.
- Authentication fails when provider is missing or disabled.

## Rollout

1. Seed enterprise providers in staging.
2. Validate SCIM sync and role resolution behavior with test tenants.
3. Enable authentication endpoint for federated clients.
4. Integrate with session/API key issuance in follow-up increments.
