# LLD 49: Broader Browser Engine Coverage and Cross-Browser Parity Tests

## Feature

Needed + Partial #42: Add broader browser engine coverage and cross-browser parity tests.

## Scope

Expand browser worker and CI configuration to support multiple browser engines and verify that the CI lane exercises cross-browser parity expectations.

- Add engine configuration in Helm values for browser worker.
- Propagate selected engines to browser worker deployment environment.
- Expand browser-worker CI workflow to run parity checks.
- Add test coverage that validates engine configuration and workflow wiring.

This increment focuses on control-plane/deployment-level parity guarantees, not full runtime behavioral emulation across browser engines.

## Data and Control Design

- Helm values introduce `browserWorker.engines` list (default: `chromium`, `firefox`, `webkit`).
- Browser worker deployment sets environment variables:
  - `PLAYWRIGHT_BROWSERS`
  - `PLAYWRIGHT_PRIMARY_BROWSER`
- CI workflow introduces a dedicated `Run cross-browser parity tests` step.

## Workflow Design

1. Configure browser engines via Helm values per environment.
2. Render deployment template with engine list exposed to worker container.
3. CI deploys chart and waits for worker/control-plane readiness.
4. CI executes existing integration tests plus cross-browser parity tests.

## Failure Policy

- Empty engine list is considered invalid for chart rendering tests.
- Missing parity step in CI workflow fails unit test guard.
- Missing engine env wiring in deployment template fails unit test guard.

## Rollout

1. Land config/template/test changes with parity checks enabled in CI.
2. Tune environment overlays (dev/prod) with desired engine sets.
3. Incrementally extend runtime browser-worker behavior tests in follow-up increments.
