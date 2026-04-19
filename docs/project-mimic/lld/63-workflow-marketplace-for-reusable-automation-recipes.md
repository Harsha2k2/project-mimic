# LLD 63: Workflow Marketplace for Reusable Automation Recipes

## Feature

Strategic Improvements #56: Add workflow marketplace for reusable automation recipes.

## Scope

Introduce a marketplace service for reusable automation recipes with tenant install and execution management.

- Add recipe registry APIs with category/tag metadata and versioning.
- Add tenant recipe install APIs with parameter overrides.
- Add workflow run API for installed recipes with dry-run support.
- Add run history APIs for tenant-scoped observability.
- Support in-memory and JSON-file persistence.
- Expose versioned and legacy API routes with RBAC, audit, metering, and realtime events.

This increment focuses on control-plane recipe lifecycle and deterministic run records, not external orchestration engines.

## Data and Control Design

- Recipe fields:
  - `recipe_id`
  - `title`
  - `category`
  - `description`
  - `steps[{index,action,description,parameters}]`
  - `tags[]`
  - `min_role`
  - `version`
  - `published`
  - `created_at`, `updated_at`
- Install fields:
  - `install_id`
  - `tenant_id`
  - `recipe_id`
  - `recipe_version`
  - `parameters`
  - `enabled`
  - `created_at`, `updated_at`
- Run fields:
  - `run_id`
  - `tenant_id`
  - `install_id`
  - `recipe_id`
  - `recipe_version`
  - `initiated_by`
  - `dry_run`
  - `step_results[]`
  - `status`
  - `started_at`, `finished_at`

## Workflow Design

1. Admin upserts published recipe definitions.
2. Operator browses recipes and installs selected recipe for tenant.
3. Operator triggers run for install (dry-run or execute mode).
4. Service records per-step run outcomes and persists run history.
5. Operators list/fetch workflow runs for auditability and operations.

## Failure Policy

- Empty recipe/install identifiers are rejected.
- Recipes must include at least one valid action step.
- Installs require existing recipe and unique install ID.
- Runs fail when install is missing, disabled, or tenant-mismatched.
- Run/read operations remain tenant-scoped.

## Rollout

1. Seed baseline recipes for common runbook automation.
2. Enable tenant installs and dry-run execution in staging.
3. Validate run history and role gating behavior.
4. Integrate with approval and governance workflows in follow-up increments.
