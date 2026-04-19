# LLD 27: End-to-End Tests with Real Browser Workers in CI

## Feature

Needed + Missed #20: Add end-to-end tests with real browser workers in CI.

## Scope

Add a CI lane that deploys the Helm chart into a temporary Kubernetes cluster and exercises the existing integration tests against the live workload.

- Start a disposable Kubernetes cluster in CI.
- Install the Project Mimic Helm release so browser worker, control plane, and Triton resources are real pods.
- Run the existing integration tests against the live environment.
- Tear down the temporary cluster after the job ends.

This increment focuses on CI execution and environment realism, not on adding a new UI automation framework.

## Test Contract

The lane should verify:

- Helm deploys the control plane and browser worker deployments successfully.
- The environment serves Triton inference through the integration harness.
- Existing replay and deterministic mimetic tests continue to pass in a live deployment context.

## Workflow Design

1. Start a kind cluster.
2. Install Helm chart into the `project-mimic` namespace.
3. Wait for the browser-worker and control-plane deployments to become ready.
4. Run integration tests.
5. Delete the cluster automatically at job end.

## Failure Policy

- Cluster bootstrap failures fail the job.
- Helm install or rollout readiness failures fail the job.
- Integration test failures fail the job.

## Rollout

1. Run on pull requests and main branch pushes.
2. Keep the lane separate from unit tests to avoid slowing normal development.
3. Expand the integration set as more real-worker behaviors are added.
