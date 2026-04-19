# LLD 29: Load and Stress Tests with Capacity Thresholds as Release Gates

## Feature

Needed + Missed #22: Add load and stress tests with capacity thresholds as release gates.

## Scope

Add a benchmark-style release gate that runs the existing benchmark harness and compares the results against explicit capacity thresholds.

- Run the deterministic benchmark path.
- Capture score and latency metrics for each task.
- Fail the gate when capacity thresholds are exceeded.
- Publish the benchmark report for review.

This increment focuses on release gating and stress validation, not on a new synthetic load-generation tool.

## Threshold Contract

`config/performance-thresholds.yml` contains:

- `min_average_score`
- `max_task_elapsed_ms`
- `max_average_elapsed_ms`
- `deterministic_seed`

## Workflow Design

1. Load thresholds.
2. Run the benchmark harness.
3. Write a benchmark report artifact.
4. Compare the report to thresholds.
5. Fail if score or latency exceeds the allowed budget.

## Failure Policy

- Missing or malformed thresholds fail the gate.
- Benchmark regressions fail the gate.
- Missing report artifact fails the gate.

## Rollout

1. Start by recording metrics without failing the job.
2. Tighten the threshold once the steady-state baseline is known.
3. Gate production releases after the baseline stabilizes.
