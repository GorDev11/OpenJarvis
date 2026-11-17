//! Opt-in Colibri/Qwen3.6 integration. No silent model downloads.
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tauri::State;
use tokio::sync::Mutex;

const MODELS_URL: &str = "http://127.0.0.1:19000/v1/models";
const HEALTH_URL: &str = "http://127.0.0.1:19000/health";

#[derive(Default)]
pub(crate) struct ColibriSetupState(pub(crate) Arc<Mutex<SetupProcess>>);

#[derive(Default)]
pub(crate) struct SetupProcess {
    running: bool,
    error: Option<String>,
}

#[derive(serde::Serialize)]
pub(crate) struct ColibriStatus {
    ready: bool,
    installing: bool,
    model: Option<String>,
    message: String,
    error: Option<String>,
    log_tail: String,
}

fn data_dir() -> PathBuf {
    #[cfg(target_os = "windows")]
    let base = std::env::var_os("LOCALAPPDATA").map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(super::home_dir()).join("AppData/Local"));
    #[cfg(not(target_os = "windows"))]
    let base = std::env::var_os("XDG_DATA_HOME").map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(super::home_dir()).join(".local/share"));
    base.join("OpenJarvis").join("Colibri")
}

fn find_qwen36(value: &serde_json::Value) -> Option<String> {
    value.get("data")?.as_array()?.iter()
        .filter_map(|m| m.get("id")?.as_str())
        .find(|id| {
            let s = id.to_ascii_lowercase();
            s == "qwen3.6-colibri"
                || ((s.contains("qwen36") || s.contains("qwen3.6")
                    || s.contains("qwen3-6"))
                    && (s.contains("35b") || s.contains("35-b")))
        })
        .map(str::to_string)
}

/// Require the model in an actual /v1/models response, not just any open port.
pub(crate) async fn probe_model() -> Result<String, String> {
    let client = reqwest::Client::builder().timeout(Duration::from_secs(4))
        .build().map_err(|e| e.to_string())?;
    let health = client.get(HEALTH_URL).send().await
        .map_err(|e| format!("Colibri health check failed: {e}"))?;
    if !health.status().is_success() {
        return Err(format!("Colibri is loading or unavailable: HTTP {}", health.status()));
    }
    let health_data: serde_json::Value = health.json().await
        .map_err(|e| format!("Invalid Colibri health response: {e}"))?;
    if health_data.get("status").and_then(serde_json::Value::as_str) != Some("ok") {
        return Err("Colibri engine is not ready.".into());
    }
    let response = client.get(MODELS_URL).send().await
        .map_err(|e| format!("Colibri not reachable on 127.0.0.1:19000: {e}"))?;
    if !response.status().is_success() {
        return Err(format!("Colibri /v1/models returned {}", response.status()));
    }
    let result: serde_json::Value = response.json().await
        .map_err(|e| format!("Invalid model list: {e}"))?;
    find_qwen36(&result).ok_or_else(|| "Qwen3.6-35B-A3B is not loaded in Colibri.".into())
}

pub(crate) async fn wait_for_model(duration: Duration) -> Result<String, String> {
    let deadline = tokio::time::Instant::now() + duration;
    let mut last = String::new();
    while tokio::time::Instant::now() < deadline {
        match probe_model().await { Ok(id) => return Ok(id), Err(e) => last = e }
        tokio::time::sleep(Duration::from_secs(3)).await;
    }
    Err(last)
}

fn log_tail() -> String {
    let Ok(mut file) = std::fs::File::open(data_dir().join("install.log")) else {
        return String::new();
    };
    let Ok(len) = file.metadata().map(|m| m.len()) else { return String::new(); };
    let _ = file.seek(SeekFrom::Start(len.saturating_sub(4000)));
    let mut bytes = Vec::new();
    let _ = file.read_to_end(&mut bytes);
    let raw = String::from_utf8_lossy(&bytes);
    raw.chars().rev().take(2600).collect::<String>().chars().rev().collect()
}

#[tauri::command]
pub(crate) async fn colibri_status(state: State<'_, ColibriSetupState>)
    -> Result<ColibriStatus, String>
{
    let process = state.0.lock().await;
    let installing = process.running;
    let error = process.error.clone();
    drop(process);
    let model = probe_model().await.ok();
    let ready = model.is_some();
    Ok(ColibriStatus {
        ready, installing, model, error, log_tail: log_tail(),
        message: if ready { "Colibri Qwen3.6 ready".into() }
        else if installing { "Installing Qwen3.6-35B-A3B (23 GB, resumable)".into() }
        else { "Colibri is not running".into() },
    })
}

/// Explicit user click initiates a verified/pinned external setup script.
#[tauri::command]
pub(crate) async fn start_colibri_setup(state: State<'_, ColibriSetupState>)
    -> Result<(), String>
{
    if probe_model().await.is_ok() { return Ok(()); }
    let root = super::find_project_root().ok_or(
        "OpenJarvis source was not found; update main first.".to_string()
    )?;
    let script = root.join("scripts/setup_colibri_qwen36.py");
    if !script.is_file() {
        return Err("Colibri setup script not present in installed main source.".into());
    }
    std::fs::create_dir_all(data_dir()).map_err(|e| e.to_string())?;
    let log = std::fs::OpenOptions::new().create(true).write(true).truncate(true)
        .open(data_dir().join("install.log")).map_err(|e| e.to_string())?;
    let stderr = log.try_clone().map_err(|e| e.to_string())?;
    let mut process = state.0.lock().await;
    if process.running { return Err("Colibri installation already running.".into()); }
    let mut command = tokio::process::Command::new(super::resolve_bin("uv"));
    command.args(["run", "--no-sync", "python"]).arg(&script)
        .current_dir(root)
        .stdout(std::process::Stdio::from(log))
        .stderr(std::process::Stdio::from(stderr));
    super::prepare_subprocess_for_appimage(&mut command);
    let mut child = super::spawn_owned_child(&mut command)
        .map_err(|e| format!("Could not start Colibri: {e}"))?;
    process.running = true;
    process.error = None;
    drop(process);

    let shared = state.0.clone();
    tauri::async_runtime::spawn(async move {
        let output = child.wait().await;
        let mut status = shared.lock().await;
        status.running = false;
        status.error = match output {
            Ok(code) if code.success() => None,
            Ok(code) => Some(format!("Colibri installer exited with {code}. See install log.")),
            Err(err) => Some(format!("Colibri installer failed: {err}")),
        };
    });
    Ok(())
}

/// Relaunch installed Colibri when selected. Never installs on startup.
pub(crate) async fn start_if_installed() -> Result<(), String> {
    if probe_model().await.is_ok() { return Ok(()); }
    // Do not attempt a second model server while Colibri reloads after a
    // temporary engine failure. Its /health returns 503 "restarting".
    if let Ok(client) = reqwest::Client::builder().timeout(Duration::from_secs(3)).build() {
        if let Ok(res) = client.get(HEALTH_URL).send().await {
            if let Ok(value) = res.json::<serde_json::Value>().await {
                if matches!(value.get("status").and_then(serde_json::Value::as_str),
                    Some("ok" | "restarting")) {
                    return Ok(());
                }
            }
        }
    }
    let launcher = data_dir().join("source/c/coli");
    if !launcher.is_file() {
        return Err("Colibri is not installed. Use Install in Settings first.".into());
    }
    let root = super::find_project_root().ok_or("OpenJarvis source missing".to_string())?;
    let mut cmd = tokio::process::Command::new(super::resolve_bin("uv"));
    cmd.args(["run", "--no-sync", "python"]).arg(&launcher)
        .args(["start", "--background", "--no-browser"])
        .current_dir(root)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    super::prepare_subprocess_for_appimage(&mut cmd);
    let child = super::spawn_owned_child(&mut cmd).map_err(|e| e.to_string())?;
    let output = tokio::time::timeout(Duration::from_secs(75), child.wait_with_output())
        .await.map_err(|_| "Colibri start timed out".to_string())?
        .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(format!("Colibri start failed: {}",
            String::from_utf8_lossy(&output.stderr).chars().take(500).collect::<String>()));
    }
    Ok(())
}

#[derive(serde::Serialize)]
pub(crate) struct ColibriToolCheck { success: bool, detail: String }

#[tauri::command]
pub(crate) async fn colibri_test_tools() -> Result<ColibriToolCheck, String> {
    let model = probe_model().await?;
    let client = reqwest::Client::builder().timeout(Duration::from_secs(120))
        .build().map_err(|e| e.to_string())?;
    let response = client.post("http://127.0.0.1:19000/v1/chat/completions")
        .json(&serde_json::json!({
            "model":model, "stream":false, "temperature":0, "max_tokens":384,
            "messages":[{"role":"user","content":"Use calculator to compute 17+25."}],
            "tools":[{"type":"function","function":{"name":"calculator",
                "description":"Compute a mathematical expression",
                "parameters":{"type":"object","properties":{"expression":{"type":"string"}},
                              "required":["expression"]}}}],
            "tool_choice":"required"
        }))
        .send().await.map_err(|e| e.to_string())?;
    if !response.status().is_success() {
        return Err(format!("Colibri tool API returned {}", response.status()));
    }
    let value: serde_json::Value = response.json().await.map_err(|e| e.to_string())?;
    let success = value.pointer("/choices/0/message/tool_calls")
        .and_then(serde_json::Value::as_array)
        .is_some_and(|xs| xs.iter().any(|t| t.pointer("/function/name")
            .and_then(serde_json::Value::as_str) == Some("calculator")));
    Ok(ColibriToolCheck { success,
        detail: if success { "Model emitted calculator tool_calls.".into() }
        else { "Model answered without calling calculator; tool use was not verified.".into() },
    })
}

#[cfg(test)]
mod tests {
    use super::find_qwen36;

    #[test]
    fn only_chooses_qwen36_35b_from_live_model_list() {
        assert_eq!(find_qwen36(&serde_json::json!({"data":[{"id":"qwen3.6-colibri"}]})),
            Some("qwen3.6-colibri".into()));
        assert_eq!(find_qwen36(&serde_json::json!({"data":[{"id":"qwen3.6-35b-a3b"}]})),
            Some("qwen3.6-35b-a3b".into()));
        assert!(find_qwen36(&serde_json::json!({"data":[{"id":"qwen3.5:9b"}]})).is_none());
    }
}
