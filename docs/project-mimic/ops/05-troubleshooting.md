# Troubleshooting Guide

## API Returns 409 On Session Step

- Cause: Session reached a terminal state.
- Fix: Use reset endpoint or create a new session.

## Session Restore Missing Checkpoint

- Cause: Checkpoint store has no entry for session id.
- Fix: Verify session id and checkpoint store configuration.

## Triton Inference Errors

- Cause: Endpoint unavailable, non-JSON response, or circuit open.
- Fix:
  - Check `TRITON_ENDPOINT` and network path.
  - Verify host allowlist and mTLS settings.
  - Inspect reliability metrics and retry behavior.

## Identity Rotation Too Frequent

- Cause: High risk signal or proxy health degradation.
- Fix:
  - Review risk inputs and thresholds.
  - Check quarantine windows and health history.

## Flaky CI Tests

- Cause: Timing-sensitive or environment-sensitive tests.
- Fix:
  - Run `.github/workflows/flaky-detection.yml`.
  - Inspect `.github/flaky-tests.txt` and quarantine unstable tests until fixed.
