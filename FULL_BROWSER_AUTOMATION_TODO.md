# Full Live Browser Automation TODO

This document describes the concrete work required to move Project Mimic from its current session simulation/prototype stage into a fully integrated live browser automation platform.

## 1. Browser Worker Runtime
- [ ] Add a browser worker service implementation
  - [ ] Create a Node.js service for browser worker orchestration
  - [ ] Install and configure Playwright runtime dependencies
  - [ ] Build a worker container image with browser binaries and Node runtime
- [ ] Add browser worker sidecar bridge
  - [ ] Create a Rust/CDP sidecar for low-level event emission
  - [ ] Wire sidecar communication between Node.js worker and Playwright
- [ ] Add browser worker health and readiness probes
  - [ ] Expose liveness/readiness endpoints
  - [ ] Integrate with Kubernetes deployment manifests

## 2. Session Allocation and Worker Binding
- [ ] Implement session-to-worker binding logic
  - [ ] Allocate sessions to live browser worker pods
  - [ ] Persist worker/session assignment metadata
  - [ ] Handle session reconnect and worker failover
- [ ] Add queueing for pending browser sessions
  - [ ] Support pending session queue when workers are busy
  - [ ] Emit queue metrics and backpressure signals

## 3. Browser Launch and Navigation
- [ ] Implement browser context launch
  - [ ] Start Chromium via Playwright in the browser worker
  - [ ] Create isolated browser contexts for each session
- [ ] Implement navigation commands
  - [ ] Add support for `page.goto(url)` from the control plane
  - [ ] Support navigation retries and error recovery
- [ ] Add browser page lifecycle management
  - [ ] Close pages and contexts cleanly at session end
  - [ ] Handle browser worker restarts without leaking resources

## 4. Screenshot Capture Pipeline
- [ ] Add screenshot capture in browser worker
  - [ ] Capture full page or viewport screenshots as bytes
  - [ ] Tag screenshots with session and step metadata
- [ ] Stream screenshots to vision inference
  - [x] Send live screenshot payloads to the vision/Triton client
  - [x] Store screenshot artifacts for debugging and replay
- [ ] Add screenshot-based operator observability
  - [x] Expose screenshot artifact links in the operator console

## 5. DOM Snapshot Ingestion
- [ ] Add DOM capture from Playwright
  - [ ] Extract DOM tree, node metadata, bounding boxes, and visibility
  - [ ] Capture layout information and node identity
- [ ] Send DOM payloads to the decision pipeline
  - [x] Normalize DOM snapshot payloads for the vision/engine layer
  - [ ] Ensure DOM snapshots are consistent with screenshots
- [ ] Add DOM snapshot storage and replay support
  - [ ] Persist snapshots for failed session analysis

## 6. Playwright/CDP Bridge and Action Execution
- [ ] Implement real action dispatch
  - [ ] Map click, type, wait, and navigation actions to Playwright/CDP commands
  - [ ] Support pointer movement, click offsets, and keyboard events
- [ ] Add acknowledgement and retry handling
  - [ ] Confirm browser actions completed successfully
  - [ ] Retry transient failures on browser commands
- [ ] Add action-level safety guards
  - [ ] Prevent unsafe DOM operations
  - [ ] Enforce navigation and timeout constraints

## 7. Real Page-to-Action Grounding
- [ ] Implement live grounding logic
  - [ ] Ground chosen UI entities to real page coordinates
  - [ ] Resolve DOM node references in live browser context
- [ ] Add confidence and fallback handling
  - [ ] Fall back when target node is stale or missing
  - [ ] Re-run vision grounding after navigation or layout change
- [ ] Add grounding traceability
  - [ ] Record which screenshot/DOM snapshot led to each action
  - [ ] Expose grounding evidence for debugging

## 8. Vision Inference Integration
- [ ] Connect browser screenshots to Triton inference
  - [ ] Send live screenshot payloads to `vision/triton_client.py`
  - [ ] Handle model responses in the runtime path
- [ ] Add runtime entity extraction flow
  - [ ] Parse detected UI entities from vision outputs
  - [ ] Emit entity and DOM candidates for planner decisions
- [ ] Support hybrid inference caching
  - [ ] Cache repeated screenshots or repeated element detections

## 9. Full End-to-End Browser Worker Flow
- [ ] Implement end-to-end session execution loop
  - [ ] Goal → browser worker allocation → screenshot/DOM capture → decision → action → next step
  - [ ] Continue until goal completed, max steps, or failure
- [ ] Add session checkpointing with real browser state
  - [ ] Save browser session state and recovery checkpoints
  - [ ] Support rollback to last good state on recoverable error
- [ ] Add goal completion and failure handling
  - [ ] Detect goal completion from browser state or task metadata
  - [ ] Mark sessions completed, failed, or expired appropriately

## 10. Testing and Validation
- [ ] Add unit tests for browser worker runtime
  - [ ] Test browser worker startup and action dispatch logic
  - [ ] Test screenshot and DOM payload generation
- [ ] Add integration tests with real browser workers
  - [ ] Add CI workflow for browser worker end-to-end tests
  - [ ] Add smoke tests for screenshot/DOM ingest and action execution
- [ ] Add cross-browser parity tests
  - [ ] Validate Chrome, Firefox, WebKit worker configurations
  - [ ] Ensure browser worker behavior is consistent across engines

## 11. Deployment and Infra
- [ ] Verify Helm manifests for browser worker components
  - [ ] Validate `deploy/helm/project-mimic/templates/browser-worker-deployment.yaml`
  - [ ] Ensure browser worker env vars like `PLAYWRIGHT_BROWSERS` are set
- [ ] Add KEDA scaling and worker autoscaling validation
  - [ ] Validate `keda-scalers.yaml` for browser worker scaling rules
  - [ ] Add browser-worker scaling smoke tests
- [ ] Add browser worker readiness/load testing
  - [ ] Confirm browser worker pods can start at scale
  - [ ] Validate startup times and resource utilization

## 12. Observability and Reliability
- [ ] Add browser worker instrumentation
  - [ ] Expose worker metrics, action latency, screenshot latency
  - [ ] Add worker error and retry counters
- [ ] Add artifact-based debugging
  - [ ] Store screenshots, DOM snapshots, and action traces
  - [ ] Surface artifacts in the operator console
- [ ] Add failure remediation automation
  - [ ] Detect browser worker hangs and self-heal
  - [ ] Add circuit breakers for unhealthy page sites

## 13. Roadmap and gating
- [ ] Complete Stage 1 browser worker integration
- [ ] Validate with real browser worker CI tests
- [ ] Harden for production by adding governance, retry, and observability
- [ ] Promote from prototype to beta release once end-to-end live browser automation is stable
