//! Explicit, fail-closed update path for the user's own OpenJarvis main checkout.
//!
//! Git source updates can update Python code and restart the managed backend.
//! They cannot replace the already compiled Tauri frontend/Windows executable.
//! Future desktop binary upgrades must use signed installer releases separately.

use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::State;
use tokio::process::Command;

use super::{start_managed_boot, SharedBackend, SharedStatus};

const SOURCE_URL: &str = "https://github.com/GorDev11/OpenJarvis.git";
const PRIMARY_BRANCH: &str = "main";
const MAX_GIT_OUTPUT: usize = 4096;

#[derive(Debug, Serialize)]
pub(crate) struct MainUpdateInfo {
    current_sha: String,
    latest_sha: String,
    branch: String,
    update_available: bool,
    can_update: bool,
    message: String,
}

fn parse_main_sha(output: &str) -> Result<String, String> {
    let line = output
        .lines()
        .find(|line| line.ends_with("\trefs/heads/main"))
        .ok_or("GitHub main branch was not found")?;
    let sha = line
        .split_whitespace()
        .next()
        .ok_or("GitHub did not return a commit SHA")?;
    if sha.len() != 40 || !sha.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("GitHub returned an invalid commit SHA".into());
    }
    Ok(sha.into())
}

fn accepted_origin(origin: &str) -> bool {
    origin.trim().trim_end_matches('/') == SOURCE_URL
        || origin.trim().trim_end_matches('/') == "https://github.com/GorDev11/OpenJarvis"
}

fn checkout_root() -> Result<PathBuf, String> {
    if !super::INSTALL_SCOPED_BACKEND {
        return Err("GitHub main updates are available only in the isolated OpenJarvis desktop build".into());
    }
    let exe = std::env::current_exe()
        .map_err(|e| format!("Cannot locate desktop executable: {e}"))?;
    let install_dir = exe.parent().ok_or("Missing desktop install directory")?;
    let expected = install_dir.join("src");
    if !expected.join("pyproject.toml").is_file() || !expected.join(".git").exists() {
        return Err(format!(
            "Desktop source checkout was not found at {}",
            expected.display()
        ));
    }
    let actual = std::fs::canonicalize(&expected)
        .map_err(|e| format!("Cannot inspect desktop source: {e}"))?;
    let intended = std::fs::canonicalize(install_dir.join("src"))
        .map_err(|e| format!("Cannot verify desktop source: {e}"))?;
    if actual != intended {
        return Err("Refusing to update an unrelated Git checkout".into());
    }
    Ok(expected)
}

async fn git(root: &Path, args: &[&str], timeout: u64) -> Result<String, String> {
    let mut command = Command::new(super::resolve_bin("git"));
    command.args(args).current_dir(root).kill_on_drop(true);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt as _;
        command.as_std_mut().creation_flags(0x0800_0000);
    }
    let result = tokio::time::timeout(Duration::from_secs(timeout), command.output())
        .await
        .map_err(|_| format!("Git command timed out: {}", args.first().unwrap_or(&"git")))?
        .map_err(|e| format!("Could not run Git: {e}"))?;
    if !result.status.success() {
        let stderr = String::from_utf8_lossy(&result.stderr);
        let excerpt: String = stderr.chars().take(MAX_GIT_OUTPUT).collect();
        return Err(format!(
            "Git {} failed: {}",
            args.first().unwrap_or(&""),
            excerpt.trim()
        ));
    }
    Ok(String::from_utf8_lossy(&result.stdout).trim().to_string())
}

async fn inspect_local_checkout(root: &Path) -> Result<(String, String, bool), String> {
    let origin = git(root, &["remote", "get-url", "origin"], 10).await?;
    if !accepted_origin(&origin) {
        return Err("Refusing update: origin is not GorDev11/OpenJarvis on GitHub".into());
    }
    let branch = git(root, &["branch", "--show-current"], 10).await?;
    if branch != PRIMARY_BRANCH && branch != "feature/armenian-voice" {
        return Err(format!(
            "Checkout is on {branch:?}; only main or the previous Armenian branch can migrate"
        ));
    }
    let dirty = !git(root, &["status", "--porcelain", "--untracked-files=normal"], 15)
        .await?
        .is_empty();
    let sha = git(root, &["rev-parse", "HEAD"], 10).await?;
    Ok((sha, branch, dirty))
}

async fn remote_main_sha(root: &Path) -> Result<String, String> {
    // Use a pinned HTTPS repository, not a user-supplied URL or arbitrary origin.
    let output = git(
        root,
        &["ls-remote", SOURCE_URL, "refs/heads/main"],
        20,
    )
    .await?;
    parse_main_sha(&output)
}

#[tauri::command]
pub(crate) async fn check_main_update() -> Result<MainUpdateInfo, String> {
    let root = checkout_root()?;
    let (current_sha, branch, dirty) = inspect_local_checkout(&root).await?;
    let latest_sha = remote_main_sha(&root).await?;
    let available = current_sha != latest_sha || branch != PRIMARY_BRANCH;
    let can_update = available && !dirty;
    let message = if dirty {
        "Local source files were modified. Back up or commit changes before updating.".into()
    } else if available {
        "New OpenJarvis main source is available. Updating restarts the Python backend; desktop UI changes require a new signed installer.".into()
    } else {
        "Main source is up to date.".into()
    };
    Ok(MainUpdateInfo {
        current_sha,
        latest_sha,
        branch,
        update_available: available,
        can_update,
        message,
    })
}

async fn fast_forward_main(root: &Path, expected_sha: &str) -> Result<(), String> {
    let (current_sha, branch, dirty) = inspect_local_checkout(root).await?;
    if dirty {
        return Err("Local checkout contains changes; update cancelled without overwriting files".into());
    }
    let shallow = root.join(".git").join("shallow").is_file();
    let fetch: Vec<&str> = if shallow {
        vec!["fetch", "--no-tags", "--unshallow", "origin", "main"]
    } else {
        vec!["fetch", "--no-tags", "origin", "main"]
    };
    git(root, &fetch, 180).await?;
    let fetched = git(root, &["rev-parse", "FETCH_HEAD"], 10).await?;
    if fetched != expected_sha {
        return Err("GitHub main changed during update; check for updates again".into());
    }
    // Reject all history rewrites, divergent local commits and unrelated checkout states.
    git(root, &["merge-base", "--is-ancestor", &current_sha, &fetched], 20).await?;
    if branch == PRIMARY_BRANCH {
        git(root, &["merge", "--ff-only", &fetched], 90).await?;
    } else {
        let local_main = git(
            root,
            &["show-ref", "--verify", "--quiet", "refs/heads/main"],
            10,
        )
        .await;
        if local_main.is_ok() {
            // A preexisting local main branch must also be an ancestor.
            let main_sha = git(root, &["rev-parse", "refs/heads/main"], 10).await?;
            git(root, &["merge-base", "--is-ancestor", &main_sha, &fetched], 20).await?;
            git(root, &["switch", "main"], 20).await?;
            git(root, &["merge", "--ff-only", &fetched], 90).await?;
        } else {
            git(root, &["switch", "-c", "main", &fetched], 45).await?;
        }
    }
    Ok(())
}

#[tauri::command]
pub(crate) async fn apply_main_update(
    expected_sha: String,
    backend: State<'_, SharedBackend>,
    status: State<'_, SharedStatus>,
    update_gate: State<'_, super::SharedSourceUpdateGate>,
) -> Result<String, String> {
    let _guard = update_gate.lock().await;
    let root = checkout_root()?;
    let (current_sha, _, dirty) = inspect_local_checkout(&root).await?;
    if dirty {
        return Err("Local edits detected. Update cancelled without changing files.".into());
    }
    let latest = remote_main_sha(&root).await?;
    if latest != expected_sha {
        return Err("A newer GitHub commit is available. Check for updates again.".into());
    }
    if current_sha == latest {
        // Still migrate the old branch name to main when necessary.
        let (_, branch, _) = inspect_local_checkout(&root).await?;
        if branch == PRIMARY_BRANCH {
            return Ok(latest);
        }
    }
    // Do not mutate the checkout with a running, owned backend. We only stop
    // processes tracked by the desktop, never an arbitrary listener on :8000.
    backend.lock().await.stop_all().await;
    let outcome = fast_forward_main(&root, &latest).await;
    // Start the normal managed boot again even if Git update failed. Boot
    // performs uv sync and confirms service readiness before use.
    start_managed_boot(backend.inner().clone(), status.inner().clone()).await;
    outcome.map(|()| latest)
}

#[cfg(test)]
mod tests {
    use super::{accepted_origin, parse_main_sha};

    #[test]
    fn only_expected_github_origin_is_accepted() {
        assert!(accepted_origin("https://github.com/GorDev11/OpenJarvis.git"));
        assert!(accepted_origin("https://github.com/GorDev11/OpenJarvis"));
        assert!(!accepted_origin("https://github.com/another/repo.git"));
        assert!(!accepted_origin("file:///tmp/local-repo"));
    }

    #[test]
    fn parses_exact_main_ref_only() {
        let sha = "0123456789abcdef0123456789abcdef01234567";
        assert_eq!(
            parse_main_sha(&format!("{sha}\trefs/heads/main")).unwrap(),
            sha
        );
        assert!(parse_main_sha(&format!("{sha}\trefs/heads/main-other")).is_err());
        assert!(parse_main_sha("not-a-sha\trefs/heads/main").is_err());
    }
}
