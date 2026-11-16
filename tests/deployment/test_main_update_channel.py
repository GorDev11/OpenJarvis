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
    assert 'https://github.com/GorDev11/OpenJarvis.git' in source
    assert '"merge-base", "--is-ancestor"' in source
    assert '"merge", "--ff-only"' in source
    assert '"status", "--porcelain"' in source
    assert "stop_all().await" in source
    assert "start_managed_boot(" in source
    for forbidden in ["reset --hard", "clean -fd", "git checkout --force"]:
        assert forbidden not in source


def test_chat_surfaces_main_update_notification() -> None:
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    widget = (FRONTEND / "MainSourceUpdate.tsx").read_text(encoding="utf-8")
    assert "<MainSourceUpdate />" in app
    assert "CHECK_EVERY_MS = 10 * 60 * 1000" in widget
    assert "apply_main_update" in widget
    assert "check_main_update" in widget


def test_unsigned_preview_never_installs_unsigned_desktop_update() -> None:
    assert "VITE_OPENJARVIS_NO_UPDATER=1" in PREVIEW_MODE.read_text(
        encoding="utf-8"
    )
    assert "VITE_OPENJARVIS_NO_UPDATER=0" in RELEASE_MODE.read_text(
        encoding="utf-8"
    )
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert "TAURI_SIGNING_PUBLIC_KEY" in workflow
    assert "createUpdaterArtifacts" in workflow
    assert "desktop-main/latest.json" in workflow
    assert "frontend/**" in workflow
    assert "github.com/open-jarvis/OpenJarvis" not in workflow
