"""Read-only Windows system checks (no real host inspection)."""

from __future__ import annotations

import base64
import json
import subprocess
from types import SimpleNamespace

from openjarvis.tools import system_diagnostics as diag


def test_tool_spec_is_read_only_and_bounded() -> None:
    spec = diag.SystemDiagnosticsTool().spec
    assert spec.name == "system_diagnostics"
    assert spec.requires_confirmation is False
    assert spec.required_capabilities == ["file:read"]
    assert "READ ONLY" in spec.description


def test_non_windows_is_a_clear_failure(monkeypatch) -> None:
    monkeypatch.setattr(diag.sys, "platform", "linux")
    result = diag.SystemDiagnosticsTool().execute()
    assert result.success is False
    assert "Windows" in result.content


def test_windows_script_is_fixed_read_only_and_json_is_preserved(monkeypatch) -> None:
    monkeypatch.setattr(diag.sys, "platform", "win32")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        payload = {
            "operating_system": {"caption": "Windows 11"},
            "recent_system_errors_24h": [],
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(diag.subprocess, "run", fake_run)
    result = diag.SystemDiagnosticsTool().execute()

    assert result.success
    assert json.loads(result.content)["operating_system"]["caption"] == "Windows 11"
    command = captured["command"]
    assert command[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    script = base64.b64decode(command[4]).decode("utf-16-le")
    for required in (
        "Get-CimInstance Win32_OperatingSystem",
        "Get-CimInstance Win32_Processor",
        "Get-Process",
        "Get-WinEvent",
    ):
        assert required in script
    for forbidden in (
        "Set-Service",
        "Stop-Service",
        "Remove-Item",
        "Clear-EventLog",
        "winget install",
    ):
        assert forbidden not in script
    assert captured["kwargs"]["timeout"] <= 35
    assert captured["kwargs"]["check"] is False


def test_bad_output_and_timeout_are_real_failures(monkeypatch) -> None:
    monkeypatch.setattr(diag.sys, "platform", "win32")
    monkeypatch.setattr(
        diag.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="not-json",
            stderr="",
        ),
    )
    assert not diag.SystemDiagnosticsTool().execute().success

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=35)

    monkeypatch.setattr(diag.subprocess, "run", timeout)
    result = diag.SystemDiagnosticsTool().execute()
    assert not result.success
    assert "failed" in result.content.lower()
