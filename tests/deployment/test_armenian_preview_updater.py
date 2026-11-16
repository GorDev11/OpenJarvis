"""The Armenian preview must never inherit the stable updater channel."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
PREVIEW_CONFIG = ROOT / "frontend" / "src-tauri" / "tauri.armenian-preview.conf.json"
PREVIEW_ENV = ROOT / "frontend" / ".env.armenian-preview"
BUILD_SCRIPT = ROOT / "scripts" / "build-armenian-desktop.ps1"
UPDATE_CHECKER = (
    ROOT / "frontend" / "src" / "components" / "Desktop" / "UpdateChecker.tsx"
)
SETTINGS_PAGE = ROOT / "frontend" / "src" / "pages" / "SettingsPage.tsx"


def test_preview_replaces_stable_updater_endpoints_and_disables_frontend_poll() -> None:
    preview = json.loads(PREVIEW_CONFIG.read_text(encoding="utf-8"))

    assert preview["identifier"] != "com.openjarvis.desktop"
    assert preview["bundle"]["createUpdaterArtifacts"] is False
    # Tauri combines --config files using JSON Merge Patch. An empty array
    # replaces, rather than inherits, the stable endpoint list.
    assert preview["plugins"]["updater"]["endpoints"] == []
    assert "active" not in preview["plugins"]["updater"]
    assert (
        preview["build"]["beforeBuildCommand"] == "npm run build:tauri:armenian-preview"
    )
    assert "VITE_OPENJARVIS_NO_UPDATER=1" in PREVIEW_ENV.read_text(encoding="utf-8")
    assert "isUpdaterBuildDisabled()" in UPDATE_CHECKER.read_text(encoding="utf-8")
    assert "updaterBuildDisabled" in SETTINGS_PAGE.read_text(encoding="utf-8")


def test_local_preview_build_accepts_descendant_worktrees() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "merge-base --is-ancestor" in script
    assert '$branch -ne "feature/armenian-voice"' not in script
