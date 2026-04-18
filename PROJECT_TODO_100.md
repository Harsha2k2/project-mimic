# Project Mimic 100-Item Implementation Backlog

This backlog is organized feature-by-feature, each with five concrete subtasks.

## Feature 01: Repository Standards and Governance

1. [x] Define branch naming and commit message conventions.
2. [x] Add CODEOWNERS with review ownership by module.
3. [x] Add pull request template with test checklist.
4. [x] Add issue templates for bug, feature, and incident.
5. [x] Add conventional release note labels and triage workflow.

## Feature 02: Core Data Models Hardening

6. [x] Add strict validation for all public Pydantic models.
7. [x] Add schema version field to API payload models.
8. [x] Add model serialization compatibility tests.
9. [x] Add explicit model error code mapping rules.
10. [x] Add migration notes for any model-breaking changes.

## Feature 03: Session Lifecycle and State Durability

11. [x] Add session expiration policy with configurable TTL.
12. [x] Persist session checkpoints in Redis for crash recovery.
13. [x] Add explicit session status transitions and guard rules.
14. [x] Add stale session scavenger background task.
15. [x] Add tests for reset, restore, and session expiry behavior.

## Feature 04: Decision Orchestrator Expansion

16. [x] Add pluggable strategy interface for site-specific policies.
17. [x] Implement retry budget manager with per-state caps.
18. [x] Add confidence calibration layer before action selection.
19. [x] Add fallback branch selection scoring and tie-break rules.
20. [x] Add orchestrator replay log for step-by-step debugging.

## Feature 05: Vision Pipeline Robustness

21. [x] Add OCR normalization for locale-specific symbols.
22. [x] Add entity deduplication across near-identical boxes.
23. [x] Add temporal cache keyed by frame similarity hash.
24. [x] Add confidence threshold policy per entity role.
25. [x] Add test fixtures for dynamic popovers and overlays.

## Feature 06: Mimetic Layer and Rust Bridge

26. [x] Define Rust to Python bridge contract for event stream.
27. [x] Add jitter profiles for desktop and mobile behavior sets.
28. [x] Add typo and correction strategy with bounded probabilities.
29. [x] Add movement profile presets tuned by viewport size.
30. [x] Add integration tests for deterministic replay mode.

## Feature 07: API Surface Maturity

31. [x] Add API version prefix and deprecation handling policy.
32. [x] Add request id propagation and response correlation ids.
33. [x] Add structured API error contract with machine codes.
34. [x] Add pagination and filters for session listing endpoints.
35. [x] Add OpenAPI examples for critical decision endpoints.

## Feature 08: gRPC Runtime Implementation

36. [x] Implement SessionService server handlers from proto.
37. [x] Implement VisionService server handlers from proto.
38. [x] Implement MimeticService server handlers from proto.
39. [x] Implement OrchestratorService server handlers from proto.
40. [x] Add gRPC contract tests for request and response shapes.

## Feature 09: Queue and Worker Orchestration

41. [x] Add task queue abstraction for action job dispatch.
42. [x] Add worker lease model with heartbeat renewal.
43. [x] Add dead-letter queue handling and replay command.
44. [x] Add idempotency key checks on all worker tasks.
45. [x] Add end-to-end tests for queue recovery scenarios.

## Feature 10: Identity and Proxy Management

46. [x] Add proxy pool persistence with health history.
47. [x] Add weighted allocator by region and failure rate.
48. [x] Add sticky identity policy with cool-down windows.
49. [x] Add identity rotation audit trail and reason codes.
50. [x] Add tests for proxy quarantine and unquarantine flow.

## Feature 11: Policy and Compliance Controls

51. [x] Add policy rule registry with priority ordering.
52. [x] Add policy simulation mode for dry-run evaluations.
53. [x] Add jurisdiction-based policy override support.
54. [x] Add policy decision explanation payloads for audit.
55. [x] Add tests for conflicting policy resolution behavior.

## Feature 12: Observability and Tracing

56. [x] Add OpenTelemetry tracing for API and orchestrator.
57. [x] Add p95 and p99 latency histograms per endpoint.
58. [x] Add per-feature success rate metrics and dashboards.
59. [x] Add trace correlation from goal to action emission.
60. [x] Add tests validating metrics endpoint field stability.

## Feature 13: Reliability and Recovery

61. [x] Add circuit breaker for unstable external dependencies.
62. [x] Add exponential backoff with jitter for transient errors.
63. [x] Add checkpoint rollback and resume workflow.
64. [x] Add failure taxonomy with standardized error classes.
65. [x] Add chaos tests for worker restart and timeout paths.

## Feature 14: Security and Secrets

66. [ ] Add secret loading abstraction for local and cloud.
67. [ ] Add token redaction in logs and exception traces.
68. [ ] Add mTLS configuration model for internal gRPC traffic.
69. [ ] Add allowlist validation for outbound target hosts.
70. [ ] Add tests ensuring sensitive values never leak to logs.

## Feature 15: Kubernetes and Scaling

71. [ ] Add Helm chart skeleton for all runtime components.
72. [ ] Add HPA and KEDA parameter overrides by environment.
73. [ ] Add GPU node affinity profiles for Triton workloads.
74. [ ] Add pod disruption budgets for critical services.
75. [ ] Add manifest tests for env-specific overlay rendering.

## Feature 16: Testing Infrastructure Expansion

76. [ ] Add contract test suite for API and gRPC parity.
77. [ ] Add snapshot tests for baseline output stability.
78. [ ] Add integration environment with ephemeral services.
79. [ ] Add mutation test pass for critical decision code.
80. [ ] Add flaky test detection and quarantine workflow.

## Feature 17: Artifacts and Data Pipeline

81. [ ] Add artifact writer abstraction for screenshots and traces.
82. [ ] Add retention policy and cleanup scheduler.
83. [ ] Add metadata index for fast replay lookup.
84. [ ] Add data integrity checks for uploaded artifacts.
85. [ ] Add tests for artifact write failure fallback behavior.

## Feature 18: Baseline Evaluation and Benchmarks

86. [ ] Add benchmark command with per-task timing metrics.
87. [ ] Add deterministic seed mode across all planners.
88. [ ] Add comparison report between deterministic and model modes.
89. [ ] Add score trend history output in JSON format.
90. [ ] Add tests for benchmark reproducibility tolerances.

## Feature 19: Developer Experience and Documentation

91. [ ] Add architecture decision record template and index.
92. [ ] Add contributor quickstart with local runbook.
93. [ ] Add troubleshooting guide for common failure modes.
94. [ ] Add module-level docs for orchestrator and vision internals.
95. [ ] Add docs validation checks in CI workflow.

## Feature 20: Release and Production Readiness

96. [ ] Add semantic version release script and changelog automation.
97. [ ] Add production readiness checklist with hard gates.
98. [ ] Add blue-green rollout runbook for API and workers.
99. [ ] Add rollback validation checklist with smoke tests.
100. [ ] Add final launch review template with sign-off owners.
