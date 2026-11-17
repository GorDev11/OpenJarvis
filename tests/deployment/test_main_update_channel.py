"""Safeguards for the owner's main-only update channels."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
DESKTOP = ROOT / "frontend" / "src-tauri" / "src"
RELEASE_MODE = ROOT / "frontend" / ".env.armenian-release"
PREVIEW_MODE = ROOT / "frontend" / ".env.armenian-preview"
WORKFLOW = ROOT / ".github" / "workflows" / "main-desktop-signed.yml"
FRONTEND = ROOT / "frontend" / "src" / "components" / "Desktop"


def test_installed_preview_clones_main_not_feature_branch() -> None:
    launcher = (DESKTOP / "lib.rs").read_text(encoding="utf-8")
    assert 'const DESKTOP_SOURCE_BRANCH: Option<&str> = Some("main");' in launcher
    assert "main_updates::check_main_update," in launcher
    assert "main_updates::apply_main_update," in launcher


def test_git_main_update_is_fast_forward_and_does_not_reset() -> None:
    source = (DESKTOP / "main_updates.rs").read_text(encoding="utf-8")
    assert 'const PRIMARY_BRANCH: &str = "main";' in source
    assert "https://github.com/GorDev11/OpenJarvis.git" in source
    assert '"merge-base", "--is-ancestor"' in source
    assert '"merge", "--ff-only"' in source
    assert '"status", "--porcelain"' in source
    assert "stop_all().await" in source
    assert "start_managed_boot(" in source
    for forbidden in ["reset --hard", "clean -fd", "git checkout --force"]:
        assert forbidden not in source


def test_chat_surfaces_main_update_notification() -> None:
    layout = (ROOT / "frontend" / "src" / "components" / "Layout.tsx").read_text(
        encoding="utf-8"
    )
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "<MainSourceUpdate />" in layout
    assert "CHECK_EVERY_MS = 15 * 1000" in widget
    assert "apply_main_update" in widget
    assert "check_main_update" in widget


def test_unsigned_preview_never_installs_unsigned_desktop_update() -> None:
    assert "VITE_OPENJARVIS_NO_UPDATER=1" in PREVIEW_MODE.read_text(encoding="utf-8")
    assert "VITE_OPENJARVIS_NO_UPDATER=0" in RELEASE_MODE.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert "TAURI_SIGNING_PUBLIC_KEY" in workflow
    assert "createUpdaterArtifacts" in workflow
    assert "desktop-main/latest.json" in workflow
    assert "frontend/**" in workflow
    assert "github.com/open-jarvis/OpenJarvis" not in workflow


def test_unified_update_card_downloads_signed_binary_then_syncs_backend() -> None:
    """On Windows the native installer closes the app; sync comes first."""
    source = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    handler = source.split("  const update = useCallback", 1)[1].split(
        "  if (!isTauri()) return null;", 1
    )[0]
    assert "await release.download(" in handler
    assert "'check_main_update'" in handler
    assert "'apply_main_update'" in handler
    assert "await release.install({ restartAfterInstall: true })" in handler
    assert (
        handler.index("await release.download(")
        < handler.index("'check_main_update'")
        < handler.index("'apply_main_update'")
        < handler.index("await release.install({ restartAfterInstall: true })")
    )
    assert "event.event === 'Started'" in handler
    assert "event.data?.contentLength" in handler
    assert "if (!source.can_update)" in handler
    assert "await invoke<string>('apply_main_update'" in handler


def test_only_one_visible_update_card_and_preview_cannot_install_binary() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    preferences = (FRONTEND / "UpdateChecker.tsx").read_text(encoding="utf-8")
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "<UpdateChecker />" not in app
    assert "export function UpdateChecker()" not in preferences
    assert "isUpdaterBuildDisabled()" in widget
    assert "const release = signedUpdate.current" in widget
    assert "await release.install({ restartAfterInstall: true })" in widget
    assert "CHECK_SIGNED_EVERY_MS = 60 * 1000" in widget


def test_signed_rust_tests_require_built_tauri_assets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.index("npm run build:tauri:armenian-release") < workflow.index(
        "cargo test --lib --features armenian-preview"
    )
    assert "frontend/dist/index.html" in workflow


def test_main_update_checks_quickly_without_overlapping_requests() -> None:
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "CHECK_EVERY_MS = 15 * 1000" in widget
    assert "checking.current" in widget
    assert "window.setInterval" in widget
    assert "window.addEventListener('focus'" in widget
    assert "window.addEventListener('online'" in widget
    assert "document.addEventListener('visibilitychange'" in widget
    assert "window.removeEventListener('focus'" in widget
    assert "document.removeEventListener('visibilitychange'" in widget
    assert "setLastCheckedAt" in widget


def test_main_update_alert_is_visible_in_layout_without_manual_checks() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    layout = (ROOT / "frontend" / "src" / "components" / "Layout.tsx").read_text(
        encoding="utf-8"
    )
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "<MainSourceUpdate />" not in app
    assert '<div className="relative z-30 shrink-0">' in layout
    assert "<MainSourceUpdate />" in layout
    assert 'role="status"' in widget
    assert 'aria-live="polite"' in widget
    assert "max-w-[520px]" in widget
    assert "pointer-events-none" in widget
    assert "Նոր թարմացում կա" in widget
    assert "Ավտոմատ ստուգում" in widget
    assert "onClick={() => void check()}" not in widget


def test_expected_backend_restart_hides_only_transient_connection_error() -> None:
    layout = (ROOT / "frontend" / "src" / "components" / "Layout.tsx").read_text(
        encoding="utf-8"
    )
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "apiReachable === false && !backendRestarting" in layout
    assert "openjarvis-backend-update" in layout
    assert "openjarvis-backend-ready" in layout
    assert "openjarvis-backend-timeout" in layout
    assert "graceDeadline = Date.now() + 5 * 60 * 1000" in layout
    assert "stage === 'waiting' && reachable" in layout
    assert "window.setInterval" in layout
    assert "openjarvis-backend-ready" in widget
    assert "openjarvis-backend-timeout" in widget
    assert "detail: 'updating'" in widget
    assert "detail: 'waiting'" in widget
    assert "Backend-ը վերագործարկվում է" in widget
    assert "Թարմացնել ամբողջ ծրագիրը" in widget
    assert "Թարմացնել միայն Backend-ը" in widget


def test_signed_bootstrap_is_explicit_and_reuses_owner_keys() -> None:
    script = (ROOT / "scripts" / "enable-desktop-auto-updates.ps1").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "scripts" / "enable-desktop-auto-updates.cmd").read_text(
        encoding="utf-8"
    )
    assert "gh auth login" in script
    assert "TAURI_SIGNING_PRIVATE_KEY" in script
    assert "TAURI_SIGNING_PUBLIC_KEY" in script
    assert "if (-not (Test-Path $keyPath))" in script
    assert "gh workflow run main-desktop-signed.yml" in script
    assert "enable-desktop-auto-updates.ps1" in installer
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Verify manifest and signed updater payload" in workflow
    assert '"requireSignedVersion"' in workflow
    assert 'installMode = "passive"' in workflow


def test_signed_auto_install_requires_opt_in_and_stays_idle_safe() -> None:
    preferences = (FRONTEND / "UpdateChecker.tsx").read_text(encoding="utf-8")
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    settings = (ROOT / "frontend" / "src" / "pages" / "SettingsPage.tsx").read_text(
        encoding="utf-8"
    )
    assert "return localStorage.getItem(AUTO_INSTALL_KEY) !== '1'" in preferences
    assert "60_000" in widget
    assert "isStreaming" in widget
    assert "openjarvis-auto-install-setting-changed" in widget
    assert "window.confirm(" in settings
    assert "Activate signed updates (once)" in settings
    assert "launch_signed_update_setup" in settings
