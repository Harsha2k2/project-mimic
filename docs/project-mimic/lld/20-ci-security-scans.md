# LLD 20: CI Security Scans

## Feature

Needed + Missed #13: Add CI security scans for SAST, dependency CVEs, and container image vulnerabilities.

## Scope

Add a dedicated CI job that runs three independent security checks:

- SAST over repository code.
- Dependency vulnerability scan for Python packages.
- Container filesystem scan for the repository image.

This increment focuses on detection in CI, not on automatic remediation or policy enforcement.

## Tooling

- SAST: Semgrep with default security rules.
- Dependency scan: pip-audit.
- Container scan: Trivy filesystem scan against the repository Dockerfile context.

## CI Design

1. Check out repository source.
2. Set up Python 3.12.
3. Install security scanning tools.
4. Run Semgrep against `src`, `tests`, and `tools`.
5. Run pip-audit against the installed dependency set.
6. Run Trivy against the repository workspace.

## Failure Policy

- Any high or critical finding fails the job.
- Lower-severity findings are visible in logs but do not fail the pipeline.
- The job runs on pull requests and pushes to `main`.

## Rollout

1. Introduce the job in advisory mode.
2. Triage initial findings and suppress accepted false positives.
3. Tighten gates once the repo is clean.
