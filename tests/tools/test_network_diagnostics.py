"""Read-only Windows network checks (no real network access)."""

from __future__ import annotations

import base64
import json
import subprocess
from types import SimpleNamespace

from openjarvis.tools import network_diagnostics as diag


def test_tool_spec_is_read_only():
    tool = diag.NetworkDiagnosticsTool()
    spec = tool.spec
    assert spec.name == "network_diagnostics"
    assert spec.requires_confirmation is False
    assert "READ ONLY" in spec.description
    assert not spec.required_capabilities


def test_non_windows_is_a_clear_failure(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "linux")
    result = diag.NetworkDiagnosticsTool().execute()
    assert result.success is False
    assert "Windows" in result.content


def test_windows_queries_are_fixed_and_data_is_parsed(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "win32")
    capture = {}

    def fake_run(command, **kwargs):
        capture["command"] = command
        capture["kwargs"] = kwargs
        payload = {"dns_resolution": "OK", "observed_neighbors": []}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(diag.subprocess, "run", fake_run)
    result = diag.NetworkDiagnosticsTool().execute()
    assert result.success
    assert json.loads(result.content)["dns_resolution"] == "OK"
    cmd = capture["command"]
    assert cmd[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]
    assert cmd[3] == "-EncodedCommand"
    script = base64.b64decode(cmd[4]).decode("utf-16-le")
    assert "Get-NetNeighbor" in script
    assert "Get-NetIPConfiguration" in script
    assert "Resolve-DnsName" in script
    for forbidden in ("Remove-Net", "Set-Dns", "/flushdns", "Restart-Net"):
        assert forbidden not in script
    assert capture["kwargs"]["timeout"] <= 20
    assert capture["kwargs"]["check"] is False


def test_bad_windows_output_is_reported_not_invented(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "win32")
    monkeypatch.setattr(
        diag.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="not JSON", stderr=""
        ),
    )
    result = diag.NetworkDiagnosticsTool().execute()
    assert not result.success
    assert "failed" in result.content.lower()


def test_timeout_does_not_hang_tool(monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "win32")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=20)

    monkeypatch.setattr(diag.subprocess, "run", timeout)
    result = diag.NetworkDiagnosticsTool().execute()
    assert result.success is False
    assert "failed" in result.content.lower()
