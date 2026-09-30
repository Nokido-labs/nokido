use spin_sdk::http::{IntoResponse, Request, Response, Method};
use spin_sdk::http_component;
use serde_json::json;

#[http_component]
fn handle_health(req: Request) -> anyhow::Result<impl IntoResponse> {
    if req.method() != &Method::Get {
        return Ok(Response::builder()
            .status(405)
            .header("content-type", "application/json; charset=utf-8")
            .body(json!({"error": "method_not_allowed"}).to_string())
            .build());
    }

    let response_body = json!({
        "status": "ok",
        "version": "wasm-spin-0.1.0",
        "backend": "wasmtime-wasip2",
        "route": "/health",
        "timestamp": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
    });

    Ok(Response::builder()
        .status(200)
        .header("content-type", "application/json; charset=utf-8")
        .body(response_body.to_string())
        .build())
}
