# LLD 06: Orchestrator Internals

## Scope

This module details internals of the orchestrator runtime in `src/project_mimic/orchestrator`.

## Core Components

- `DecisionOrchestrator`: candidate selection and step lifecycle execution.
- `ActionStateMachine`: deterministic transition graph with retry control.
- `RetryBudgetManager`: per-state retry budgets and exhaustion handling.
- `SiteStrategyRegistry`: site-specific confidence calibration and fallback logic.

## Execution Path

1. Collect grounded candidates.
2. Calibrate confidence using strategy + global calibrator.
3. Select viable candidate or fallback candidate.
4. Run action cycle through state machine.
5. Record replay events and trace spans for diagnostics.

## Failure Handling

- Retry budget exhaustion transitions to `FAIL`.
- Low-confidence candidates trigger fallback branch.
- Replay log and tracer spans provide post-mortem evidence.
