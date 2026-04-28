use mimetic::sidecar::{
    build_keystroke_plan,
    build_pointer_plan,
    KeystrokePlanPayload,
    PointerPlanPayload,
};
use mimetic::Point;

#[test]
fn pointer_plan_uses_minimum_steps() {
    let payload = PointerPlanPayload {
        start: Point { x: 10.0, y: 10.0 },
        target: Point { x: 200.0, y: 140.0 },
        viewport_width: 1280,
        viewport_height: 720,
        dwell_ms: 60,
        steps: Some(1),
    };

    let response = build_pointer_plan(payload);
    assert!(response.events.len() >= 4);
    assert_eq!(response.events.last().unwrap().event_type, "up");
}

#[test]
fn keystroke_plan_emits_keydown_and_keyup() {
    let payload = KeystrokePlanPayload {
        text: "hi".to_string(),
        base_delay_ms: 40,
    };

    let response = build_keystroke_plan(payload);
    assert_eq!(response.events.len(), 4);
    assert_eq!(response.events[0].event_type, "keydown");
    assert_eq!(response.events[1].event_type, "keyup");
}
