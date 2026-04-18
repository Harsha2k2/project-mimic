use mimetic::{plan_bezier_path, synthesize_keystrokes, Point, PointerPlanRequest};

#[test]
fn pointer_path_stays_in_viewport() {
    let request = PointerPlanRequest {
        start: Point { x: 0.0, y: 0.0 },
        target: Point { x: 5000.0, y: 5000.0 },
        viewport_width: 300,
        viewport_height: 200,
        dwell_ms: 60,
    };

    let events = plan_bezier_path(&request, 10);
    for event in events.iter().filter(|e| e.event_type == "move") {
        assert!(event.x >= 0.0 && event.x <= 299.0);
        assert!(event.y >= 0.0 && event.y <= 199.0);
    }
}

#[test]
fn whitespace_increases_keystroke_delay() {
    let events = synthesize_keystrokes("a a", 20);
    let keydown_events: Vec<_> = events.iter().filter(|e| e.event_type == "keydown").collect();

    let first_gap = keydown_events[1].t_ms - keydown_events[0].t_ms;
    let second_gap = keydown_events[2].t_ms - keydown_events[1].t_ms;

    assert!(first_gap >= second_gap);
}
