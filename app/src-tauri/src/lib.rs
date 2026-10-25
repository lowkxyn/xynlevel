mod updater;

use serde::Deserialize;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, LogicalSize, Manager};
use tauri_plugin_notification::NotificationExt;

const HEADER: &str = "X-XynLevel-Token";
struct Backend {
    child: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
    error: Mutex<Option<String>>,
    token: String,
    closing: AtomicBool,
    expanded_size: Mutex<Option<tauri::PhysicalSize<u32>>>,
}

#[derive(Deserialize)]
struct Ready {
    port: u16,
    pid: u32,
    version: String,
}

fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(12))
        .build()
        .map_err(|_| "Could not create the local bridge client".into())
}

fn request(
    app: &AppHandle,
    method: &str,
    route: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    let state = app.state::<Backend>();
    let port = (*state.port.lock().unwrap()).ok_or_else(|| {
        state
            .error
            .lock()
            .unwrap()
            .clone()
            .unwrap_or_else(|| "The Python bridge is starting".into())
    })?;
    // The caller selects an operation, never an address. Tokens cannot follow redirects.
    let url = format!("http://127.0.0.1:{port}{route}");
    let http = client()?;
    let mut query = if method == "GET" {
        http.get(url)
    } else {
        http.post(url)
    };
    query = query.header(HEADER, &state.token);
    if let Some(body) = body {
        query = query.json(&body);
    }
    let response = query
        .send()
        .map_err(|_| "The Python bridge is unavailable. Restart XynLevel.".to_string())?;
    if !response.status().is_success() {
        return response
            .json::<Value>()
            .ok()
            .and_then(|v| v.get("error").and_then(Value::as_str).map(str::to_owned))
            .map_or_else(|| Err("The bridge rejected this request".into()), Err);
    }
    response
        .json()
        .map_err(|_| "The bridge returned an invalid response".into())
}

fn backend_start(app: AppHandle) -> Result<(), String> {
    let directory = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "App data folder unavailable")?;
    std::fs::create_dir_all(&directory).map_err(|_| "Cannot create the app data folder")?;
    #[cfg(debug_assertions)]
    let mut command = {
        let mut c =
            Command::new(std::env::var_os("XYNLEVEL_PYTHON").unwrap_or_else(|| "python".into()));
        c.arg(std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../python/core_server.py"));
        c
    };
    #[cfg(not(debug_assertions))]
    let mut command = {
        let exe = std::env::current_exe().map_err(|_| "Cannot resolve the installed app")?;
        let path = exe
            .parent()
            .ok_or("Cannot resolve the sidecar folder")?
            .join("XynLevel-core.exe");
        Command::new(path)
    };
    command
        .arg("--data-dir")
        .arg(&directory)
        .arg("--parent-pid")
        .arg(std::process::id().to_string())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| "Cannot launch the Python bridge. In development, install python/requirements.txt; in an installed build check antivirus quarantine.")?;
    let pid = child.id();
    let handover = child
        .stdin
        .take()
        .ok_or("Missing sidecar input pipe")
        .and_then(|mut input| {
            writeln!(input, "{}", app.state::<Backend>().token)
                .map_err(|_| "Could not authenticate the bridge")
        });
    if let Err(error) = handover {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error.into());
    }
    let stdout = child.stdout.take().ok_or("Missing bridge output pipe")?;
    {
        let state = app.state::<Backend>();
        let mut owned = state.child.lock().unwrap();
        if state.closing.load(Ordering::SeqCst) {
            let _ = child.kill();
            let _ = child.wait();
            return Err("The app is closing".into());
        }
        *owned = Some(child);
    }
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout)
            .take(4096)
            .read_line(&mut line)
            .map(|_| line);
        let _ = tx.send(result);
    });
    let line = rx
        .recv_timeout(Duration::from_secs(30))
        .map_err(|_| "Python bridge startup timed out")?
        .map_err(|_| "Cannot read Python bridge readiness")?;
    let ready: Ready = serde_json::from_str(&line).map_err(|_| {
        "Python bridge exited before readiness. Check dependencies or antivirus quarantine."
    })?;
    if ready.port == 0 || ready.pid != pid || ready.version != env!("CARGO_PKG_VERSION") {
        return Err("Python bridge identity mismatch; rebuild the sidecar".into());
    }
    *app.state::<Backend>().port.lock().unwrap() = Some(ready.port);
    let health = request(&app, "GET", "/health", None)?;
    if health["pid"].as_u64() != Some(u64::from(pid))
        || health["version"].as_str() != Some(env!("CARGO_PKG_VERSION"))
        || health["ok"] != true
    {
        return Err("Python bridge health check failed".into());
    }
    Ok(())
}

fn kill_owned(app: &AppHandle) {
    if let Some(mut child) = app.state::<Backend>().child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
        release_game_keys();
    }
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn keybd_event(vk: u8, scan: u8, flags: u32, extra: usize);
}

/// A killed bridge can't let go of the keys the bot was holding (charge Shift, W/A/D, Space), and
/// Roblox would keep running or charging. Key-ups for keys that aren't down do nothing.
#[cfg(windows)]
fn release_game_keys() {
    const KEYEVENTF_KEYUP: u32 = 0x0002;
    const KEYEVENTF_SCANCODE: u32 = 0x0008; // the bot presses by scan code, so release the same way
    for (vk, scan) in [(0xA0, 0x2A), (0x57, 0x11), (0x41, 0x1E), (0x44, 0x20), (0x20, 0x39)] {
        unsafe { keybd_event(vk, scan, KEYEVENTF_KEYUP | KEYEVENTF_SCANCODE, 0) };
    }
}

#[cfg(not(windows))]
fn release_game_keys() {}

fn close_app(app: AppHandle) {
    if app.state::<Backend>().closing.swap(true, Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(move || {
        let _ = request(
            &app,
            "POST",
            "/command",
            Some(json!({"action": "shutdown"})),
        );
        let deadline = Instant::now() + Duration::from_secs(12);
        loop {
            let exited = app
                .state::<Backend>()
                .child
                .lock()
                .unwrap()
                .as_mut()
                .map(|child| matches!(child.try_wait(), Ok(Some(_))))
                .unwrap_or(true);
            if exited || Instant::now() >= deadline {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        kill_owned(&app);
        app.exit(0);
    });
}

fn known_command(action: &str) -> bool {
    matches!(
        action,
        "start"
            | "stop"
            | "settings"
            | "reset_settings"
            | "set_window"
            | "log_start"
            | "log_stop"
            | "report_preview"
            | "report_save"
            | "export_logs"
            | "cancel_after_run"
            | "open_data"
            | "webhook_save"
            | "webhook_clear"
            | "webhook_test"
    )
}

#[tauri::command]
async fn api(app: AppHandle, action: String, payload: Option<Value>) -> Result<Value, String> {
    if action == "updater" {
        return Ok(updater::status());
    }
    if !matches!(action.as_str(), "state" | "logs") && !known_command(&action) {
        return Err("Unknown operation".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        if matches!(action.as_str(), "state" | "logs") {
            request(&app, "GET", &format!("/{action}"), None)
        } else {
            request(
                &app,
                "POST",
                "/command",
                Some(json!({"action": action, "payload": payload.unwrap_or_else(|| json!({}))})),
            )
        }
    })
    .await
    .map_err(|_| "The bridge request failed".to_string())?
}

#[tauri::command]
fn notification_access(app: AppHandle) -> Result<String, String> {
    app.notification()
        .request_permission()
        .map(|permission| format!("{permission:?}"))
        .map_err(|_| "Windows notification permission could not be requested".into())
}

#[tauri::command]
fn window_control(app: AppHandle, action: String, enabled: Option<bool>) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or("Main window unavailable")?;
    match action.as_str() {
        "close" => {
            close_app(app);
            Ok(())
        }
        "minimize" => window.minimize().map_err(|e| e.to_string()),
        // data-tauri-drag-region needs a permission core:default doesn't grant; XynMacro found the same
        // and drags from Rust on title-bar mousedown instead. Native drag keeps Aero snap working.
        "drag" => window.start_dragging().map_err(|e| e.to_string()),
        "maximize" => if window.is_maximized().unwrap_or(false) {
            window.unmaximize()
        } else {
            window.maximize()
        }
        .map_err(|e| e.to_string()),
        "pin" => window
            .set_always_on_top(enabled.unwrap_or(false))
            .map_err(|e| e.to_string()),
        "compact" => {
            if enabled.unwrap_or(false) {
                if window.is_maximized().unwrap_or(false) {
                    window.unmaximize().map_err(|e| e.to_string())?;
                }
                *app.state::<Backend>().expanded_size.lock().unwrap() =
                    Some(window.inner_size().map_err(|e| e.to_string())?);
                window
                    .set_min_size(Some(LogicalSize::new(540.0, 78.0)))
                    .map_err(|e| e.to_string())?;
                window
                    .set_size(LogicalSize::new(640.0, 78.0))
                    .map_err(|e| e.to_string())
            } else {
                window
                    .set_min_size(Some(LogicalSize::new(680.0, 520.0)))
                    .map_err(|e| e.to_string())?;
                if let Some(size) = app.state::<Backend>().expanded_size.lock().unwrap().take() {
                    window.set_size(size).map_err(|e| e.to_string())
                } else {
                    window
                        .set_size(LogicalSize::new(980.0, 700.0))
                        .map_err(|e| e.to_string())
                }
            }
        }
        _ => Err("Unknown window operation".into()),
    }
}

pub fn run() {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).expect("Secure random source unavailable");
    let token = bytes
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_notification::init())
        .manage(Backend {
            child: Mutex::new(None),
            port: Mutex::new(None),
            error: Mutex::new(None),
            token,
            closing: AtomicBool::new(false),
            expanded_size: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            api,
            window_control,
            notification_access
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Err(error) = backend_start(handle.clone()) {
                    *handle.state::<Backend>().error.lock().unwrap() = Some(error);
                    *handle.state::<Backend>().port.lock().unwrap() = None;
                    kill_owned(&handle);
                    return;
                }
                // A normal sidecar exit follows the explicitly configured close-after-run action.
                let mut notified_run = 0;
                loop {
                    std::thread::sleep(Duration::from_secs(1));
                    let state = handle.state::<Backend>();
                    if state.closing.load(Ordering::SeqCst) {
                        break;
                    }
                    let status = state
                        .child
                        .lock()
                        .unwrap()
                        .as_mut()
                        .and_then(|child| child.try_wait().ok())
                        .flatten();
                    if let Some(status) = status {
                        *state.port.lock().unwrap() = None;
                        if status.success() {
                            close_app(handle.clone());
                        } else {
                            *state.error.lock().unwrap() = Some(
                                "The Python bridge stopped unexpectedly. Restart XynLevel.".into(),
                            );
                        }
                        break;
                    }
                    if let Ok(snapshot) = request(&handle, "GET", "/state", None) {
                        if let Some(id) = snapshot["last_run"]["id"].as_u64() {
                            if id > notified_run {
                                notified_run = id;
                                if snapshot["settings"]["notifications"] == true {
                                    let _ = handle
                                        .notification()
                                        .builder()
                                        .title("XynLevel")
                                        .body(
                                            snapshot["last_run"]["reason"]
                                                .as_str()
                                                .unwrap_or("Run ended"),
                                        )
                                        .show();
                                }
                            }
                        }
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                close_app(window.app_handle().clone());
            }
        })
        .build(tauri::generate_context!())
        .expect("Cannot create XynLevel")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, code, .. } = event {
                if code.is_none() {
                    api.prevent_exit();
                    close_app(app.clone());
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_named_local_operations_are_allowed() {
        assert!(known_command("start"));
        for invalid in [
            "shutdown",
            "https://example.invalid",
            "//other",
            "../state",
            "shell",
        ] {
            assert!(!known_command(invalid));
        }
    }
    #[test]
    fn updater_cannot_contact_a_release_feed() {
        assert!(!updater::ENABLED);
        assert_eq!(updater::status()["status"], "disabled");
    }
}
