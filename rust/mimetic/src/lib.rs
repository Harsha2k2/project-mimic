//! Mimetic interaction primitives for Project Mimic.

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PointerPlanRequest {
    pub start: Point,
    pub target: Point,
    pub viewport_width: u32,
    pub viewport_height: u32,
    pub dwell_ms: u32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PointerEvent {
    pub t_ms: u32,
    pub x: f64,
    pub y: f64,
    pub event_type: &'static str,
}

#[derive(Debug, Clone, PartialEq)]
pub struct KeyEvent {
    pub t_ms: u32,
    pub key: char,
    pub event_type: &'static str,
}

pub fn plan_bezier_path(request: &PointerPlanRequest, steps: usize) -> Vec<PointerEvent> {
    assert!(steps >= 2, "steps must be >= 2");

    let dx = request.target.x - request.start.x;
    let dy = request.target.y - request.start.y;

    let control_a = Point {
        x: request.start.x + (dx * 0.33),
        y: request.start.y + (dy * 0.05),
    };
    let control_b = Point {
        x: request.start.x + (dx * 0.66),
        y: request.start.y + (dy * 0.95),
    };

    let mut out = Vec::with_capacity(steps + 2);
    for i in 0..steps {
        let t = i as f64 / (steps as f64 - 1.0);
        let eased_t = ease_in_out_cubic(t);
        let point = cubic_bezier(request.start, control_a, control_b, request.target, eased_t);
        let clamped = clamp_to_viewport(point, request.viewport_width, request.viewport_height);
        out.push(PointerEvent {
            t_ms: (t * 700.0) as u32,
            x: clamped.x,
            y: clamped.y,
            event_type: "move",
        });
    }

    out.push(PointerEvent {
        t_ms: 700 + request.dwell_ms,
        x: request.target.x,
        y: request.target.y,
        event_type: "down",
    });
    out.push(PointerEvent {
        t_ms: 740 + request.dwell_ms,
        x: request.target.x,
        y: request.target.y,
        event_type: "up",
    });

    out
}

pub fn synthesize_keystrokes(text: &str, base_delay_ms: u32) -> Vec<KeyEvent> {
    let mut out = Vec::with_capacity(text.len() * 2);
    let mut current_t = 0u32;

    for (idx, ch) in text.chars().enumerate() {
        let cadence = cadence_delay(ch, base_delay_ms, idx);
        current_t += cadence;
        out.push(KeyEvent {
            t_ms: current_t,
            key: ch,
            event_type: "keydown",
        });
        current_t += 35;
        out.push(KeyEvent {
            t_ms: current_t,
            key: ch,
            event_type: "keyup",
        });
    }

    out
}

fn cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: f64) -> Point {
    let omt = 1.0 - t;
    let omt2 = omt * omt;
    let omt3 = omt2 * omt;
    let t2 = t * t;
    let t3 = t2 * t;

    Point {
        x: (omt3 * p0.x) + (3.0 * omt2 * t * p1.x) + (3.0 * omt * t2 * p2.x) + (t3 * p3.x),
        y: (omt3 * p0.y) + (3.0 * omt2 * t * p1.y) + (3.0 * omt * t2 * p2.y) + (t3 * p3.y),
    }
}

fn ease_in_out_cubic(t: f64) -> f64 {
    if t < 0.5 {
        4.0 * t * t * t
    } else {
        1.0 - ((-2.0 * t + 2.0).powf(3.0) / 2.0)
    }
}

fn cadence_delay(ch: char, base_delay_ms: u32, idx: usize) -> u32 {
    let class_adjustment = if ch.is_whitespace() {
        120
    } else if ch.is_ascii_punctuation() {
        65
    } else if ch.is_ascii_digit() {
        45
    } else {
        25
    };

    let variation = ((idx % 5) as u32) * 7;
    base_delay_ms + class_adjustment + variation
}

fn clamp_to_viewport(point: Point, width: u32, height: u32) -> Point {
    let max_x = (width.saturating_sub(1)) as f64;
    let max_y = (height.saturating_sub(1)) as f64;
    Point {
        x: point.x.clamp(0.0, max_x),
        y: point.y.clamp(0.0, max_y),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_contains_click_events() {
        let request = PointerPlanRequest {
            start: Point { x: 10.0, y: 10.0 },
            target: Point { x: 200.0, y: 140.0 },
            viewport_width: 1280,
            viewport_height: 720,
            dwell_ms: 80,
        };

        let path = plan_bezier_path(&request, 12);
        assert!(path.len() >= 14);
        assert_eq!(path[path.len() - 2].event_type, "down");
        assert_eq!(path[path.len() - 1].event_type, "up");
    }

    #[test]
    fn keystrokes_generate_down_and_up_for_each_char() {
        let events = synthesize_keystrokes("ab", 50);
        assert_eq!(events.len(), 4);
        assert_eq!(events[0].event_type, "keydown");
        assert_eq!(events[1].event_type, "keyup");
        assert!(events[1].t_ms > events[0].t_ms);
    }
}
