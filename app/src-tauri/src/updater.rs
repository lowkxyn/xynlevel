use serde_json::{json, Value};

pub const ENABLED: bool = false;

pub fn status() -> Value {
    // TODO: provision an XynLevel-only signing key, endpoint and release process.
    // TODO: enable the optional plugin and implement checked download/install/restart.
    // Never import another product's update identity. No network call is made here.
    json!({"enabled": ENABLED, "status": "disabled", "message": "Updates are disabled for this build. TODO: configure XynLevel signing and endpoint."})
}
