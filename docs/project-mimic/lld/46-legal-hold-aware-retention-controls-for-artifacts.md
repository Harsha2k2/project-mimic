# LLD 46: Legal-Hold-Aware Retention Controls for Artifacts

## Feature

Needed + Partial #39: Add legal-hold-aware retention controls for artifacts.

## Scope

Enhance artifact retention to preserve records under legal hold while still enforcing regular retention for non-held artifacts.

- Add legal hold controls to artifact manager.
- Make age-based cleanup skip held artifacts.
- Make per-session cap cleanup preserve held artifacts and trim only non-held artifacts.
- Support listing legal holds with optional session filtering.

This increment focuses on retention safety and governance in the artifact subsystem.

## Data and Control Design

- Legal hold metadata is stored on artifact records (`legal_hold`, `legal_hold_case_id`, optional reason).
- Retention policy now includes metadata key configuration for legal-hold markers.
- Cleanup logic checks legal-hold metadata before deleting artifacts.

## Workflow Design

1. Artifact is marked with legal hold and case metadata.
2. Retention cleanup evaluates age and per-session caps.
3. Held artifacts are excluded from deletion decisions.
4. Non-held artifacts continue through normal retention cleanup paths.

## Failure Policy

- Setting legal hold requires non-empty case ID.
- Clearing legal hold removes case/reason metadata and re-enables retention eligibility.
- Missing artifact IDs still raise lookup errors from artifact index.

## Rollout

1. Enable legal hold annotations in artifact operations.
2. Apply retention with hold-aware cleanup semantics.
3. Integrate hold management with higher-level compliance workflows in future increments.
