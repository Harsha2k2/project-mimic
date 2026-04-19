# LLD 26: Deployment Pipeline Gates for Helm and Manifest Policy Checks

## Feature

Needed + Missed #19: Add deployment pipeline gates for Helm and manifest policy checks.

## Scope

Add a release gate that validates both the raw Kubernetes manifests and the Helm chart render before deployment.

- Lint the Helm chart.
- Render the chart with the repository defaults.
- Validate a policy set across raw and rendered manifests.
- Fail if unsafe or malformed deployment artifacts are detected.

This increment does not perform deployment itself; it guards the release pipeline before deployment.

## Policy Contract

The checker should enforce:

- Every deployment has a namespace.
- Every deployment has at least one container image.
- Control-plane and canary deployments use the `project-mimic` namespace.
- The canary deployment remains isolated under its own `track: canary` label.
- Worker and Triton manifests keep required resource settings and are parseable.

## Workflow Design

1. Lint Helm chart with `helm lint`.
2. Render Helm chart with `helm template`.
3. Parse raw manifests and rendered templates.
4. Apply policy checks to each document.
5. Fail the workflow on any violation.

## Failure Policy

- Missing chart or malformed YAML fails the gate.
- Missing namespace, selector mismatch, or image configuration failure fails the gate.
- Render failures fail the gate.

## Rollout

1. Start the gate as a required pre-deployment CI job.
2. Extend policy coverage as new manifests are added.
3. Reuse the checker in release automation later.
