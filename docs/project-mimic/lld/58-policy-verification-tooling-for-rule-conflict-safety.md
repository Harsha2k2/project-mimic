# LLD 58: Policy Verification Tooling for Rule-Conflict Safety

## Feature

Strategic Improvements #51: Add policy verification tooling for rule-conflict safety.

## Scope

Introduce policy verification tooling that statically analyzes tenant policy rules and reports unsafe overlaps, ambiguous precedence, and shadowed rules.

- Add tenant-scoped policy verification rule registry.
- Add deterministic conflict analysis across action, jurisdiction, auth/region constraints, and risk ranges.
- Detect conflict classes:
  - `priority_conflict` for equal-priority opposing effects.
  - `precedence_conflict` for overlapping allow/deny rules resolved only by ordering.
  - `shadowed_rule` for lower-priority rules hidden by broader higher-priority rules.
- Persist verification reports for operator review and auditability.
- Expose versioned and legacy API routes with RBAC, metering, and audit events.

This increment focuses on static policy safety checks and does not replace runtime policy decision enforcement.

## Data and Control Design

- Rule fields:
  - `rule_id`
  - `tenant_id`
  - `effect` (`allow` or `deny`)
  - `priority`
  - `action_patterns`
  - `jurisdictions`
  - `requires_authorization`
  - `requires_region_allowed`
  - `min_risk_score`
  - `max_risk_score`
  - `enabled`
  - `metadata`
  - `created_at`
  - `updated_at`
- Verification report fields:
  - `report_id`
  - `tenant_id`
  - `include_disabled`
  - `total_rules`
  - `active_rules`
  - `checked_pairs`
  - `conflict_count`
  - `severity`
  - `conflicts[]`
  - `generated_at`

Conflict severity aggregation:

- `high` when any `priority_conflict` exists.
- `medium` when no high conflicts but at least one `precedence_conflict` exists.
- `low` when only shadowed rules exist.
- `none` when no conflicts are detected.

## Workflow Design

1. Admin upserts policy verification rules for tenant policy domains.
2. Operators trigger validation to generate conflict report.
3. Service analyzes pairwise overlaps and emits categorized conflicts.
4. Report is persisted and listed for follow-up review.
5. Operators fetch specific reports for detailed remediation guidance.

## Failure Policy

- Invalid effects, selectors, risk ranges, or tenant IDs are rejected.
- Tenant-scoped reads of missing rules/reports return not found.
- Disabled rules are excluded by default and can be included explicitly.
- Verification reports remain immutable snapshots once generated.

## Rollout

1. Seed verification rules mirroring current runtime policy intents.
2. Run validation in CI and staging for policy bundles.
3. Gate high-severity conflict findings from production promotion.
4. Use report history to track policy hygiene and drift over time.
