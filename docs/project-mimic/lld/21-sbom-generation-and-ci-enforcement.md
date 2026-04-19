# LLD 21: SBOM Generation and CI Enforcement

## Feature

Needed + Missed #14: Add SBOM generation and enforcement in CI.

## Scope

Produce a software bill of materials for every CI run and fail the job if SBOM generation or validation fails.

- Generate an SPDX JSON SBOM from the repository workspace.
- Validate that the SBOM is parseable and contains the expected project component.
- Upload the SBOM as a build artifact for downstream review.

This increment does not add release-time attestation or signing; those come later.

## Tooling

- SBOM generator: Anchore SBOM Action or equivalent SPDX emitter.
- Validation: a small Python check over the generated JSON.

## CI Design

1. Check out source.
2. Generate the SBOM.
3. Parse the SBOM and verify it includes the project package name.
4. Fail if SBOM output is missing or malformed.
5. Upload the artifact for inspection.

## Failure Policy

- Missing SBOM artifact fails the job.
- Malformed JSON fails the job.
- Expected package metadata absent from the SBOM fails the job.

## Rollout

1. Add generation in advisory mode.
2. Add artifact retention and review process.
3. Tighten checks as the SBOM format stabilizes.
