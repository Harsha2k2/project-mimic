use serde::{Deserialize, Serialize};

use crate::{
    plan_bezier_path,
    synthesize_keystrokes,
    KeyEvent,
    Point,
    PointerEvent,
    PointerPlanRequest,
};

#[derive(Debug, Deserialize)]
pub struct PointerPlanPayload {
    pub start: Point,
    pub target: Point,
    pub viewport_width: u32,
    pub viewport_height: u32,
    pub dwell_ms: u32,
    pub steps: Option<usize>,
}

#[derive(Debug, Deserialize)]
pub struct KeystrokePlanPayload {
    pub text: String,
    pub base_delay_ms: u32,
}

#[derive(Debug, Serialize)]
pub struct PointerPlanResponse {
    pub events: Vec<PointerEvent>,
}

#[derive(Debug, Serialize)]
pub struct KeystrokePlanResponse {
    pub events: Vec<KeyEvent>,
}

pub fn build_pointer_plan(payload: PointerPlanPayload) -> PointerPlanResponse {
    let steps = payload.steps.unwrap_or(12).max(2);
    let request = PointerPlanRequest {
        start: payload.start,
        target: payload.target,
        viewport_width: payload.viewport_width,
        viewport_height: payload.viewport_height,
        dwell_ms: payload.dwell_ms,
    };

    PointerPlanResponse {
        events: plan_bezier_path(&request, steps),
    }
}

pub fn build_keystroke_plan(payload: KeystrokePlanPayload) -> KeystrokePlanResponse {
    KeystrokePlanResponse {
        events: synthesize_keystrokes(&payload.text, payload.base_delay_ms),
    }
}
