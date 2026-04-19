# LLD 28: Integration Lane with Real Triton/GPU Inference Path

## Feature

Needed + Missed #21: Add an integration lane with real Triton/GPU inference path.

## Scope

Add a dedicated CI lane that is intended to run on a GPU-capable runner and exercises the Triton inference path directly.

- Run on a GPU-labeled self-hosted runner.
- Start or connect to a Triton inference service endpoint.
- Execute the Triton client integration test path.
- Fail the job if the inference call does not return the expected entities.

This increment focuses on the CI lane and test execution contract rather than changing the inference client itself.

## Test Contract

The lane should verify:

- Triton client can reach the inference endpoint.
- The inference endpoint returns a valid entity payload.
- The existing end-to-end replay integration remains green alongside the Triton check.

## Workflow Design

1. Run on GPU-capable infrastructure.
2. Install Python dependencies.
3. Set the Triton endpoint required by the integration harness.
4. Run the Triton integration test and replay integration test.
5. Fail if any validation step fails.

## Failure Policy

- Missing GPU runner or endpoint configuration fails the job.
- Triton inference failures fail the job.
- Replay test failures fail the job.

## Rollout

1. Start with manual dispatch on the GPU runner.
2. Promote to pull request validation once stable.
3. Keep the lane isolated from unit tests because it depends on specialized infrastructure.
