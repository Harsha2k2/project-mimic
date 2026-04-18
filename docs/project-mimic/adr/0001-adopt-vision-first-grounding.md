# ADR-0001: Adopt Vision-First Grounding

- Status: Accepted
- Date: 2026-04-18
- Owners: Project Mimic core team

## Context

Selector-only automation is brittle across dynamic websites and anti-bot defenses. We need resilient grounding that still maps actions to DOM for traceability.

## Decision

Use vision-first entity detection as the initial action grounding source, then map to DOM nodes and coordinates for execution.

## Alternatives Considered

- DOM selector-first automation
- Pure vision coordinate-only execution
- Hybrid with selector fallback

## Consequences

- Higher robustness to DOM drift and A/B variants.
- Additional inference and calibration cost.
- Requires confidence calibration and fallback routing.

## Rollout Plan

- Keep selector fallback for low-confidence states.
- Collect replay logs and calibrate thresholds by site.

## References

- `docs/project-mimic/lld/03-visual-spatial-brain.md`
- `docs/project-mimic/lld/06-orchestrator-internals.md`
