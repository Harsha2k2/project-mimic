# LLD 52: Cluster-Level Chaos Testing (Node Loss, Network Partition, Storage Faults)

## Feature

Needed + Partial #45: Add cluster-level chaos testing (node loss, network partition, storage faults).

## Scope

Add a deterministic chaos testing suite and CI lane assertions that validate cluster-level fault scenarios through manifest- and workflow-level checks.

- Define reusable chaos scenario catalog for node, network, and storage faults.
- Add chaos plan generation and execution result model for reproducible simulations.
- Add tests for scenario coverage and failure signal contracts.
- Add CI workflow guard test ensuring explicit cluster chaos scenarios are exercised.

This increment focuses on deterministic chaos simulation and test automation contracts, not live destructive fault injection into production clusters.

## Data and Control Design

- Scenario fields:
  - `scenario_id`
  - `fault_class`
  - `target`
  - `duration_seconds`
  - `expected_signals[]`
- Supported fault classes:
  - `node_loss`
  - `network_partition`
  - `storage_fault`
- Execution report fields:
  - `run_id`
  - `started_at`, `finished_at`
  - `overall_healthy`
  - per-scenario result entries with expected signal checks

## Workflow Design

1. Build a chaos plan from predefined scenario catalog.
2. Execute deterministic simulation over each scenario.
3. Validate expected failure/recovery signals per scenario.
4. Aggregate results into a single report.
5. Fail tests if any required scenario class is missing or unhealthy.

## Failure Policy

- Unknown fault classes are rejected.
- Missing expected signals mark scenario unhealthy.
- Plan without all required fault classes fails validation.

## Rollout

1. Add chaos scenario model and tests in repository.
2. Validate in CI through dedicated chaos test coverage.
3. Evolve scenarios to drive future live-cluster chaos automation.
