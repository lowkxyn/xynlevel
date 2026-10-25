#![windows_subsystem = "windows"]

use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    env, fs,
    io::Write,
    os::windows::{fs::MetadataExt, process::CommandExt},
    path::{Component, Path, PathBuf},
    process::{Command, ExitCode},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::Duration,
};
use tao::{
    dpi::LogicalSize,
    event::{Event, WindowEvent},
    event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy},
    platform::windows::{IconExtWindows, WindowExtWindows},
    window::{Icon, WindowBuilder},
};
use tempfile::TempDir;
use winreg::{
    enums::{HKEY_CURRENT_USER, KEY_READ, KEY_WOW64_64KEY},
    RegKey,
};
use wry::{WebContext, WebViewBuilder};

const CREATE_NO_WINDOW: u32 = 0x08000000;
const SETUP: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/xyn-payload.exe"));
const HTML: &str = include_str!(concat!(env!("OUT_DIR"), "/ui.html"));
const APP_JSON: &str = include_str!("../app.json");
const VERSION: &str = include_str!(concat!(env!("OUT_DIR"), "/version.txt"));

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct App {
    name: String,
    exe: String,
    registry_key: String,
    identifier: String,
    uninstall_key: String,
}

#[derive(Debug)]
enum UiEvent {
    Request(Value),
    Update(Value),
    Complete(Result<PathBuf, String>),
}

fn message(text: &str, name: &str) {
    let wide = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
    unsafe {
        windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
            std::ptr::null_mut(),
            wide(text).as_ptr(),
            wide(name).as_ptr(),
            windows_sys::Win32::UI::WindowsAndMessaging::MB_OK
                | windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONEXCLAMATION,
        );
    }
}

fn registry_key(path: &str) -> std::io::Result<RegKey> {
    RegKey::predef(HKEY_CURRENT_USER).open_subkey_with_flags(path, KEY_READ | KEY_WOW64_64KEY)
}

fn installed_folder(app: &App) -> Option<PathBuf> {
    registry_key(&app.registry_key)
        .ok()?
        .get_value::<String, _>("")
        .ok()
        .map(PathBuf::from)
        .filter(|p| p.join(&app.exe).is_file())
}

// No shell. NSIS consumes the unquoted /D= remainder, including spaces, LAST.
fn installer_command(exe: &Path, folder: &Path, shortcuts: bool) -> Command {
    let mut cmd = Command::new(exe);
    cmd.creation_flags(CREATE_NO_WINDOW).arg("/S");
    if !shortcuts {
        cmd.arg("/NS");
    }
    cmd.raw_arg(format!("/D={}", folder.display()));
    cmd
}

fn verify_install(folder: &Path, app: &App) -> Result<(), String> {
    let complete = || -> Option<()> {
        for name in [app.exe.as_str(), "uninstall.exe"] {
            let meta = fs::symlink_metadata(folder.join(name)).ok()?;
            if !meta.is_file() || meta.len() == 0 || meta.file_attributes() & 0x400 != 0 {
                return None;
            }
        }
        let registered: String = registry_key(&app.registry_key).ok()?.get_value("").ok()?;
        let uninstall = registry_key(&app.uninstall_key).ok()?;
        let location: String = uninstall.get_value("InstallLocation").ok()?;
        let uninstaller: String = uninstall.get_value("UninstallString").ok()?;
        let version: String = uninstall.get_value("DisplayVersion").ok()?;
        let binary: String = uninstall.get_value("MainBinaryName").ok()?;
        if !same_folder(Path::new(&registered), folder)
            || !same_folder(Path::new(location.trim_matches('"')), folder)
            || !same_folder(
                Path::new(uninstaller.trim_matches('"')),
                &folder.join("uninstall.exe"),
            )
            || version != VERSION.trim()
            || binary != app.exe
        {
            return None;
        }
        Some(())
    };
    complete().ok_or_else(|| "Setup returned success but the executable, uninstaller or installation registration is incomplete. Retry setup.".into())
}

fn same_folder(a: &Path, b: &Path) -> bool {
    a.to_string_lossy()
        .trim_end_matches('\\')
        .eq_ignore_ascii_case(b.to_string_lossy().trim_end_matches('\\'))
}

fn validate_folder(text: &str, app: &App, local: &Path) -> Result<PathBuf, String> {
    let expanded = if text.to_uppercase().starts_with("%LOCALAPPDATA%\\") {
        local.join(&text[15..])
    } else {
        PathBuf::from(text)
    };
    let raw = expanded.to_string_lossy();
    if raw.contains(['"', '%', '<', '>', '|', '?', '*'])
        || raw.chars().any(|c| c.is_control())
        || !expanded.is_absolute()
        || raw.starts_with("\\\\")
        || raw.contains('/')
        || raw.encode_utf16().count() > 240
        || raw[2..].contains(':')
        || expanded
            .components()
            .any(|c| matches!(c, Component::ParentDir))
        || raw.split('\\').any(|p| p.ends_with([' ', '.']))
    {
        return Err("Choose a full local folder path, such as C:\\Apps\\YourApp. Quotes, network paths and relative paths aren't supported.".into());
    }
    let lower = raw.trim_end_matches('\\').to_lowercase();
    let protected = [
        Some(local.to_path_buf()),
        env::var_os("USERPROFILE").map(PathBuf::from),
        env::var_os("ProgramFiles").map(PathBuf::from),
    ];
    let blocked_trees = [
        Some(local.join(&app.identifier)),
        env::var_os("APPDATA").map(|p| PathBuf::from(p).join(&app.identifier)),
        env::var_os("WINDIR").map(PathBuf::from),
    ];
    if expanded.parent().is_none()
        || expanded.components().count() < 3
        || protected.into_iter().flatten().any(|p| {
            let p = p.to_string_lossy().to_lowercase();
            lower == p
        })
        || blocked_trees.into_iter().flatten().any(|p| {
            let p = p.to_string_lossy().to_lowercase();
            lower == p || lower.starts_with(&(p + "\\"))
        })
    {
        return Err("Choose a dedicated application folder. This location contains Windows, account or application data.".into());
    }
    for ancestor in expanded.ancestors() {
        if let Ok(meta) = fs::symlink_metadata(ancestor) {
            if meta.file_attributes() & 0x400 != 0 {
                return Err("Choose a folder without junctions or symbolic links.".into());
            }
        }
    }
    if expanded.exists() {
        let mut entries =
            fs::read_dir(&expanded).map_err(|e| format!("Can't read the install folder: {e}"))?;
        if entries.next().is_some() && !expanded.join(&app.exe).is_file() {
            return Err(format!(
                "Choose an empty folder or an existing {} installation.",
                app.name
            ));
        }
    }
    Ok(expanded)
}

fn extract_setup(temp: &TempDir) -> Result<PathBuf, String> {
    let path = temp.path().join("xyn-payload.exe");
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|e| format!("Couldn't prepare setup: {e}"))?;
    file.write_all(SETUP)
        .map_err(|e| format!("Couldn't extract setup: {e}"))?;
    file.sync_all().map_err(|e| e.to_string())?;
    Ok(path)
}

fn clean_profile(profile: TempDir) {
    // Only the exact directory created by tempfile is eligible, never a caller path.
    let path = profile.path().to_path_buf();
    if profile.close().is_err() {
        // WebView2's child process can briefly keep cache files open after controller close.
        for _ in 0..20 {
            thread::sleep(Duration::from_millis(100));
            if !path.exists() || fs::remove_dir_all(&path).is_ok() {
                break;
            }
        }
    }
}

fn run_install(
    folder: PathBuf,
    shortcuts: bool,
    proxy: &EventLoopProxy<UiEvent>,
    app: &App,
) -> Result<PathBuf, String> {
    let temp = tempfile::Builder::new()
        .prefix("xynlevel-setup-")
        .tempdir()
        .map_err(|e| e.to_string())?;
    let setup = extract_setup(&temp)?;
    let mut child = installer_command(&setup, &folder, shortcuts)
        .spawn()
        .map_err(|e| format!("Couldn't start setup: {e}"))?;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                if !status.success() {
                    return Err(format!("Setup exited with code {}. Close XynLevel, check permissions and free disk space, then retry.", status.code().unwrap_or(-1)));
                }
                verify_install(&folder, app)?;
                let _ = proxy.send_event(UiEvent::Update(json!({"kind":"progress","pct":100,"step":"Finishing","detail":"Installation verified"})));
                thread::sleep(Duration::from_millis(400));
                return Ok(folder);
            }
            Err(e) => {
                // Keep the extracted backend alive until its process exits.
                let _ = child.wait();
                return Err(format!("Couldn't read the setup result: {e}"));
            }
            Ok(None) => {}
        }
        let _ = proxy.send_event(UiEvent::Update(json!({"kind":"progress","step":"Installing XynLevel","detail":"Please wait while setup completes"})));
        thread::sleep(Duration::from_millis(200));
    }
}

fn dry_install(proxy: EventLoopProxy<UiEvent>, folder: PathBuf, fail: bool) {
    for _ in 0..40 {
        let _ = proxy.send_event(UiEvent::Update(json!({"kind":"progress","step":"Installing XynLevel","detail":"Preview only - no installation"})));
        thread::sleep(Duration::from_millis(100));
    }
    let result = if fail {
        Err(
            "Preview: setup exited with code 2. Check permissions and free disk space, then retry."
                .into(),
        )
    } else {
        Ok(folder)
    };
    let _ = proxy.send_event(UiEvent::Complete(result));
}

fn fallback(app: &App, dry: bool) -> ExitCode {
    message(
        if dry {
            "WebView2 isn't available. Preview stopped without starting the NSIS installer."
        } else {
            "Setup requires Microsoft Edge WebView2 Runtime. Install the runtime and reopen setup. No installation was started."
        },
        &app.name,
    );
    ExitCode::FAILURE
}

fn main() -> ExitCode {
    let app: App = serde_json::from_str(APP_JSON).unwrap();
    let args: Vec<String> = env::args().skip(1).collect();
    let dry = args.iter().any(|a| a == "--dry-run");
    if args.iter().any(|a| {
        !matches!(
            a.as_str(),
            "--dry-run"
                | "--dry-run-error"
                | "--dry-run-fresh"
                | "--dry-run-update"
                | "--test-no-webview"
        )
    }) || (!dry
        && args
            .iter()
            .any(|a| a.starts_with("--dry-run-") || a == "--test-no-webview"))
    {
        message(
            "Supported options: --dry-run [--dry-run-error] [--dry-run-fresh|--dry-run-update] [--test-no-webview]",
            &app.name,
        );
        return ExitCode::FAILURE;
    }
    if args.iter().any(|a| a == "--test-no-webview") {
        return fallback(&app, dry);
    }
    let Some(local) = (if dry {
        Some(PathBuf::from(r"C:\Preview\LocalAppData"))
    } else {
        env::var_os("LOCALAPPDATA").map(PathBuf::from)
    }) else {
        message(
            "LOCALAPPDATA is unavailable for this Windows account.",
            &app.name,
        );
        return ExitCode::FAILURE;
    };
    let installed = if dry {
        args.iter()
            .any(|a| a == "--dry-run-update")
            .then(|| local.join(&app.name))
    } else {
        installed_folder(&app)
    };
    let installed_version = if dry {
        Some("preview".to_string())
    } else {
        registry_key(&app.uninstall_key)
            .and_then(|key| key.get_value::<String, _>("DisplayVersion"))
            .ok()
    };
    let folder = installed.clone().unwrap_or_else(|| local.join(&app.name));
    let event_loop = EventLoopBuilder::<UiEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    let window = match WindowBuilder::new()
        .with_title(format!(
            "{} Setup{}",
            app.name,
            if dry { " (preview)" } else { "" }
        ))
        .with_inner_size(LogicalSize::new(720.0, 460.0))
        .with_resizable(false)
        .with_decorations(false)
        .with_visible(false)
        .with_window_icon(Icon::from_resource(1, None).ok())
        .build(&event_loop)
    {
        Ok(window) => window,
        Err(e) => {
            message(&format!("Couldn't open setup: {e}"), &app.name);
            return ExitCode::FAILURE;
        }
    };
    // A CSS radius leaves light fringes on the corners, so Windows 11 rounds the window instead.
    unsafe {
        use windows_sys::Win32::Graphics::Dwm::{
            DwmSetWindowAttribute, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND,
        };
        let preference = DWMWCP_ROUND;
        DwmSetWindowAttribute(
            window.hwnd() as _,
            DWMWA_WINDOW_CORNER_PREFERENCE as u32,
            &preference as *const _ as *const _,
            std::mem::size_of_val(&preference) as u32,
        );
    }
    let profile = match tempfile::Builder::new().prefix("xyn-webview-").tempdir() {
        Ok(temp) => temp,
        Err(e) => {
            message(&e.to_string(), &app.name);
            return ExitCode::FAILURE;
        }
    };
    let mut context = WebContext::new(Some(profile.path().to_path_buf()));
    let ipc_proxy = proxy.clone();
    let initial_data_navigation = std::cell::Cell::new(false);
    let webview = match WebViewBuilder::new_with_web_context(&mut context)
        .with_html(HTML)
        .with_devtools(false)
        .with_hotkeys_zoom(false)
        .with_initialization_script("window.addEventListener('error', e => window.ipc.postMessage(JSON.stringify({cmd:'uiError',message:e.message}))); ")
        .with_navigation_handler(move |url| {
            // WebView2 can expose NavigateToString's first document as a data URL.
            // Only that initial, embedded navigation is allowed; later data URLs are denied.
            url == "about:blank" || (url.starts_with("data:text/html;charset=utf-8;base64,")
                && !initial_data_navigation.replace(true))
        })
        .with_new_window_req_handler(|_, _| wry::NewWindowResponse::Deny)
        .with_ipc_handler(move |request| {
            if let Ok(value) = serde_json::from_str::<Value>(request.body()) {
                let _ = ipc_proxy.send_event(UiEvent::Request(value));
            }
        })
        .build(&window)
    {
        Ok(view) => view,
        Err(_) => {
            drop(window);
            return fallback(&app, dry);
        }
    };
    let mut profile = Some(profile);
    let mut webview = Some(webview);
    let mut context = Some(context);
    let busy = Arc::new(AtomicBool::new(false));
    let mut ready_folder: Option<PathBuf> = None;
    let fail = args.iter().any(|a| a == "--dry-run-error");
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        let update = |value: Value| { if let Some(view) = &webview { let _ = view.evaluate_script(&format!("window.host({value})")); } };
        match event {
            Event::UserEvent(UiEvent::Request(req)) => match req["cmd"].as_str().unwrap_or("") {
                "uiError" => {
                    message(&format!("Setup's interface couldn't load: {}", req["message"].as_str().unwrap_or("Unknown interface error")), &app.name);
                    if !busy.load(Ordering::SeqCst) { *control_flow = ControlFlow::Exit; }
                }
                "ready" => {
                    let display_folder = folder.strip_prefix(&local).map(|p| format!("%LOCALAPPDATA%\\{}", p.display()))
                        .unwrap_or_else(|_| folder.to_string_lossy().into_owned());
                    update(json!({"kind":"init","folder":display_folder,"installed":installed.is_some(),"installedVersion":installed_version})); window.set_visible(true);
                }
                "close" if !busy.load(Ordering::SeqCst) => *control_flow = ControlFlow::Exit,
                "minimise" => window.set_minimized(true),
                "drag" => { let _ = window.drag_window(); }
                "browse" if !busy.load(Ordering::SeqCst) && installed.is_none() => {
                    if let Some(path) = rfd::FileDialog::new().set_directory(&folder).pick_folder() {
                        update(json!({"kind":"folder","folder":path}));
                    }
                }
                "install" if !busy.load(Ordering::SeqCst) && ready_folder.is_none() => {
                    let destination = validate_folder(req["folder"].as_str().unwrap_or(""), &app, &local);
                    match destination {
                        Err(e) => update(json!({"kind":"error","message":e})),
                        Ok(destination) => {
                            if installed.as_ref().is_some_and(|p| !same_folder(p, &destination)) {
                                update(json!({"kind":"error","message":"Updates use the existing install folder."}));
                                return;
                            }
                            busy.store(true, Ordering::SeqCst);
                            let proxy = proxy.clone();
                            let shortcuts = req["shortcuts"].as_bool().unwrap_or(true);
                            thread::spawn(move || {
                                if dry { dry_install(proxy, destination, fail); }
                                else {
                                    let app = serde_json::from_str(APP_JSON).unwrap();
                                    let result = run_install(destination, shortcuts, &proxy, &app);
                                    let _ = proxy.send_event(UiEvent::Complete(result));
                                }
                            });
                        }
                    }
                }
                "launch" if !busy.load(Ordering::SeqCst) => {
                    if let Some(destination) = &ready_folder {
                        if dry { *control_flow = ControlFlow::Exit; }
                        else {
                            match Command::new(destination.join(&app.exe)).current_dir(destination).creation_flags(CREATE_NO_WINDOW).spawn() {
                                Ok(_) => *control_flow = ControlFlow::Exit,
                                Err(e) => update(json!({"kind":"launchError","message":format!("Installation finished, but the app couldn't start: {e}. Open it from its install folder.")})),
                            }
                        }
                    }
                }
                _ => {}
            },
            Event::UserEvent(UiEvent::Update(value)) => update(value),
            Event::UserEvent(UiEvent::Complete(result)) => {
                busy.store(false, Ordering::SeqCst);
                match result {
                    Ok(destination) => { ready_folder = Some(destination); update(json!({"kind":"done"})); }
                    Err(e) => update(json!({"kind":"error","message":e})),
                }
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                if !busy.load(Ordering::SeqCst) { update(json!({"kind":"close"})); }
            }
            Event::LoopDestroyed => {
                // These are uniquely created temporary directories, never the app's data or install tree.
                drop(webview.take());
                drop(context.take());
                if let Some(temp) = profile.take() { clean_profile(temp); }
            }
            _ => {}
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    fn app() -> App {
        serde_json::from_str(APP_JSON).unwrap()
    }
    #[test]
    fn destination_rejects_unsafe_and_data_paths() {
        let local = Path::new(r"C:\SyntheticLocal");
        for bad in [
            "",
            "relative",
            "C:\\",
            r"C:\Apps\..\Other",
            "C:\\Bad\"Path",
            r"\\server\share\app",
            r"C:\Apps\bad.",
            r"C:\SyntheticLocal\com.xynlevel.app",
            r"C:\SyntheticLocal\com.xynlevel.app\nested",
            r"C:\Apps\bad:stream",
        ] {
            assert!(validate_folder(bad, &app(), local).is_err(), "{bad}");
        }
        assert_eq!(
            validate_folder(r"%LOCALAPPDATA%\Programs\XynLevel", &app(), local).unwrap(),
            local.join(r"Programs\XynLevel")
        );
        assert!(validate_folder(r"C:\Installer Test\Example App", &app(), local).is_ok());
    }
    #[test]
    fn only_supported_flags_and_destination_last() {
        let cmd = installer_command(
            Path::new("setup.exe"),
            Path::new(r"C:\Apps With Spaces\Level"),
            false,
        );
        let rendered = format!("{cmd:?}");
        assert!(rendered.contains("/S"));
        assert!(rendered.find("/NS").unwrap() < rendered.find("/D=").unwrap());
        assert!(!rendered.contains("/R "));
        assert!(!rendered.contains("/NoDesktop"));
        assert!(!rendered.contains("/ProgressFile"));
        let enabled = installer_command(Path::new("setup.exe"), Path::new(r"C:\Apps\Level"), true);
        assert!(!format!("{enabled:?}").contains("/NS"));
    }
    #[test]
    fn registration_targets_tauri_current_user_keys() {
        assert_eq!(app().registry_key, r"Software\Xyn\XynLevel");
        assert_eq!(
            app().uninstall_key,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\XynLevel"
        );
        assert!(same_folder(
            Path::new(r"C:\Apps\XynLevel"),
            Path::new(r"c:\apps\xynlevel\")
        ));
    }
    #[test]
    fn missing_installation_never_verifies() {
        let temp = tempfile::tempdir().unwrap();
        assert!(verify_install(temp.path(), &app()).is_err());
    }
}
