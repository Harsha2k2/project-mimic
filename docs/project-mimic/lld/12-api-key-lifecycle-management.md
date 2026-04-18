# LLD 12: API Key Lifecycle Management

## Feature

Needed + Missed #5: Add API key lifecycle management (create, rotate, revoke, scope).

## Scope

This increment adds in-memory API key lifecycle controls exposed via admin endpoints.

- Create API key with role, tenant scope, and scopes list.
- List API keys (metadata only, no secret disclosure).
- Rotate API key secret.
- Revoke API key.
- Middleware authentication resolves key metadata from the key registry.

Persistent key storage, KMS-backed encryption, and external IAM federation are out-of-scope.

## API Endpoints

- `GET /api/v1/auth/keys`
- `POST /api/v1/auth/keys`
- `POST /api/v1/auth/keys/{key_id}/rotate`
- `POST /api/v1/auth/keys/{key_id}/revoke`

Legacy unversioned aliases are included with deprecation headers.

## Authorization

- Auth key lifecycle endpoints require `admin` role.
- Other route role behavior remains:
  - read-only => `viewer`
  - mutating => `operator`

## Key Registry Model

In-memory dictionaries:

- `api_key_records_by_id[key_id] -> record`
- `key_id_by_secret[secret] -> key_id`

Record fields:

- `key_id`
- `role`
- `tenant_id`
- `scopes`
- `active`
- `created_at`
- `last_rotated_at`

## Middleware Flow

1. Read `X-API-Key` secret.
2. Resolve key id from `key_id_by_secret`.
3. Load record and verify `active`.
4. Use record role/tenant/scopes for authorization and tenant scoping.

## Test Plan

1. Admin creates key; created key authenticates requests.
2. List endpoint returns metadata including newly created key.
3. Rotate endpoint issues new secret; old secret is rejected.
4. Revoke endpoint disables secret usage.
5. Non-admin key cannot call key lifecycle endpoints.

## Rollout

1. Start in-memory for local/staging.
2. Migrate to persistent encrypted key store in next security iteration.
3. Add key usage audit and expiry policies in follow-up feature.
