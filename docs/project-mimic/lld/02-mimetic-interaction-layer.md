# LLD: Mimetic Interaction Layer (Rust)

## 1) Purpose

The Mimetic Interaction Layer generates human-like pointer and keyboard behavior while preserving deterministic execution guarantees needed by distributed orchestration.

## 2) Runtime Placement

- Runs as a Rust sidecar in each Browser Worker pod.
- Exposes gRPC endpoints for pointer and keystroke planning and emission.
- Emits low-level events through a Node.js bridge into Playwright/CDP.

## 3) Crate Layout

```text
mimetic/
  src/
    lib.rs
    grpc_server.rs
    profile.rs
    pointer/
      bezier.rs
      velocity.rs
      jitter.rs
      planner.rs
    keyboard/
      cadence.rs
      typo.rs
      planner.rs
    emitter/
      cdp_bridge.rs
      event_stream.rs
```

## 4) Core Data Models

```rust
pub struct PointerPlanRequest {
    pub session_id: String,
    pub start_x: f32,
    pub start_y: f32,
    pub target_x: f32,
    pub target_y: f32,
    pub viewport_w: u32,
    pub viewport_h: u32,
    pub profile_id: String,
}

pub struct PointerEvent {
    pub t_ms: u32,
    pub x: f32,
    pub y: f32,
    pub event_type: String,
}

pub struct KeyPlanRequest {
    pub session_id: String,
    pub text: String,
    pub field_type: String,
    pub profile_id: String,
}
```

## 5) Pointer Synthesis Algorithm

1. Compute control points for cubic Bezier curve from start to target.
2. Bound control points by target size and distance to prevent unrealistic paths.
3. Apply velocity profile (minimum-jerk style) along curve arc length.
4. Add low-amplitude jitter and optional micro-corrections near target.
5. Sample dwell before click from profile distribution.
6. Emit pointer move events and click down/up with temporal spacing.

Notes:

- Overshoot-and-correct behavior is probabilistic and bounded.
- Max acceleration and jerk are clamped per profile.

## 6) Keyboard Cadence Algorithm

1. Tokenize text into words and key classes.
2. Sample inter-key intervals by key class.
3. Add word-boundary pauses and occasional cognitive pauses.
4. Optionally inject typo/backspace based on profile probability.
5. Emit keydown/keyup events preserving realistic hold time.

## 7) Behavior Profiles

Behavior profile defines stable user style for a session:

- pointer speed range
- correction frequency
- dwell distribution
- typing speed distribution
- typo rate
- pause cadence

Profile consistency is critical for cross-step realism.

## 8) gRPC Interface (Mimetic Service)

- PlanPointer(PathRequest) -> PathPlan
- EmitPointer(PathPlan) -> EmitAck
- PlanKeystrokes(KeyRequest) -> KeyPlan
- EmitKeystrokes(KeyPlan) -> EmitAck

Each request carries:

- session id
- trace id
- deadline
- policy flags

## 9) Performance and Safety

Targets:

- pointer planning p95 < 10 ms
- keyboard plan p95 < 5 ms
- event emission clock drift < 3 ms

Safety checks:

- coordinate bounds validation
- rate limiting for event floods
- deterministic replay mode for debugging

## 10) Testing

- Unit tests
  - Bezier generation edge cases.
  - Velocity profile boundary checks.
  - Typo injection constraints.
- Property tests
  - Pointer path stays within viewport.
  - Event timestamps are monotonic.
- Integration tests
  - CDP bridge ack handling under network jitter.
