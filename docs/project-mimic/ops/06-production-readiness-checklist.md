# Production Readiness Checklist

## Hard Gates (Must Pass)

- [ ] Python and Rust test suites pass on main.
- [ ] API and gRPC contract tests pass with no schema regressions.
- [ ] Security checks pass: secret redaction, allowlist validation, mTLS config review.
- [ ] Capacity checks pass for control plane, workers, and Triton autoscaling limits.
- [ ] Rollback plan and smoke tests are validated in staging.

## Release Quality Gates

- [ ] Changelog generated from semantic release script.
- [ ] Benchmark report generated with deterministic seed.
- [ ] Documentation validation job passes.
- [ ] Flaky quarantine report reviewed and triaged.

## Sign-Off Gates

- [ ] Engineering lead approval.
- [ ] SRE approval.
- [ ] Security approval.
- [ ] Product approval.
