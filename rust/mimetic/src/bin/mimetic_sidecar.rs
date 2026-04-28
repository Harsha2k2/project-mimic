use axum::{routing::get, routing::post, Json, Router};
use serde::Serialize;
use tokio::net::TcpListener;

use mimetic::sidecar::{
    build_keystroke_plan,
    build_pointer_plan,
    KeystrokePlanPayload,
    PointerPlanPayload,
};

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
}

#[derive(Serialize)]
struct InfoResponse {
    status: &'static str,
    version: &'static str,
}

fn read_port() -> u16 {
    std::env::var("SIDECAR_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(7200)
}

async fn health() -> Json<HealthResponse> {
    Json(HealthResponse { status: "ok" })
}

async fn info() -> Json<InfoResponse> {
    Json(InfoResponse {
        status: "ready",
        version: env!("CARGO_PKG_VERSION"),
    })
}

async fn pointer_plan(Json(payload): Json<PointerPlanPayload>) -> Json<mimetic::sidecar::PointerPlanResponse> {
    Json(build_pointer_plan(payload))
}

async fn keystroke_plan(Json(payload): Json<KeystrokePlanPayload>) -> Json<mimetic::sidecar::KeystrokePlanResponse> {
    Json(build_keystroke_plan(payload))
}

#[tokio::main]
async fn main() {
    let port = read_port();
    let address = std::net::SocketAddr::from(([0, 0, 0, 0], port));

    let app = Router::new()
        .route("/healthz", get(health))
        .route("/readyz", get(info))
        .route("/v1/mimetic/pointer/plan", post(pointer_plan))
        .route("/v1/mimetic/keyboard/plan", post(keystroke_plan));

    let listener = TcpListener::bind(address)
        .await
        .expect("failed to bind sidecar port");
    println!("mimetic-sidecar listening on 0.0.0.0:{port}");

    axum::serve(listener, app)
        .await
        .expect("sidecar server failed");
}
