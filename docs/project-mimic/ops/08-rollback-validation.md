# Rollback Validation Checklist

## Trigger Conditions

- Sustained elevated error rate.
- p99 latency regression beyond SLO threshold.
- Data-integrity or policy-enforcement anomalies.

## Rollback Steps

1. Shift traffic back to Blue deployment.
2. Verify API liveness/readiness and session continuity.
3. Drain Green worker queues safely.
4. Validate checkpoint rollback/resume flow.
5. Capture incident timeline and affected release metadata.

## Smoke Tests After Rollback

- [ ] Create session and step through action cycle.
- [ ] Restore and rollback checkpoint for active session.
- [ ] Execute decision click path with grounded UI sample.
- [ ] Verify metrics endpoint and trace correlation payload.
- [ ] Verify artifact write path with integrity checks.

## Completion Criteria

- Error rates return to baseline.
- Smoke tests pass.
- Incident report and follow-up issues filed.
