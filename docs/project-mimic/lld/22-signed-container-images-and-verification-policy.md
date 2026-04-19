# LLD 22: Signed Container Images and Verification Policy

## Feature

Needed + Missed #15: Add signed container images and verification policy.

## Scope

Add a CI workflow that builds the application container image, signs the pushed digest, and verifies the signature before the pipeline completes.

- Build the app image from the repository `Dockerfile`.
- Push the image to GHCR using the GitHub Actions token.
- Sign the pushed digest with cosign keyless signing.
- Verify the signature in the same workflow.

This increment covers CI enforcement and release readiness, not policy admission controllers or Kubernetes runtime enforcement.

## CI Design

1. Build and push the image to GHCR.
2. Capture the immutable image digest.
3. Sign the digest with OIDC-backed cosign keyless signing.
4. Verify the signature with the workflow identity and issuer constraints.
5. Fail if any step does not complete.

## Policy

- Only immutable digests are verified.
- The identity and issuer constraints must match the repository workflow.
- The workflow must fail on verification mismatch.

## Rollout

1. Introduce the workflow for main-branch builds.
2. Confirm GHCR publish permissions and OIDC availability.
3. Extend the same signature policy to release pipelines later.
