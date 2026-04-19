# LLD 50: Pluggable Site-Pack Packaging and Versioning Model for Strategies

## Feature

Needed + Partial #43: Add pluggable site-pack packaging/versioning model for strategies.

## Scope

Introduce a site-pack registry that versions strategy packages and supports channel promotion with optional runtime application to orchestrator site strategy mappings.

- Add site-pack registry service with in-memory and JSON-file stores.
- Add site-pack API surface for register/list/promote/channel/apply/runtime-mapping.
- Support rollout channels (`dev`, `canary`, `prod`) for site-pack assignments.
- Apply promoted active-channel site-pack strategies to orchestrator runtime mappings.
- Preserve legacy routes with deprecation headers.

This increment focuses on package/version control and controlled rollout for strategy plugins, not full dynamic artifact download/execution.

## Data and Control Design

- Site-pack version record fields:
  - `pack_id`
  - `version`
  - `strategy_class`
  - `artifact_uri`
  - `site_ids[]`
  - `metadata`
  - `created_at`
- Channel assignment fields:
  - `channel`
  - `pack_id`
  - `version`
  - `strategy_class`
  - `artifact_uri`
  - `site_ids[]`
  - `updated_at`
- Runtime application:
  - Strategy classes are resolved/imported dynamically.
  - Applied mappings are visible through runtime strategy mapping endpoint.

## Workflow Design

1. Admin registers a new site-pack version.
2. Admin lists versions to verify published records.
3. Admin promotes a version to a rollout channel.
4. If promoted channel matches active channel and auto-apply is enabled, strategy mappings are applied.
5. Admin can manually apply a channel assignment and inspect runtime mappings.

## Failure Policy

- Empty IDs/version/class/artifact URI are rejected.
- Duplicate `pack_id::version` registration is rejected.
- Promoting unknown version returns not found.
- Unsupported channel returns bad request.
- Applying assignment with unresolvable strategy class returns bad request.

## Rollout

1. Register and promote site-pack versions in `dev` first.
2. Verify runtime mapping endpoint reflects expected strategy bindings.
3. Promote to `canary` and `prod` once validation is complete.
4. Add external artifact integrity verification in a follow-up increment.
