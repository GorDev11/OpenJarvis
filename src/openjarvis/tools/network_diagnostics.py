"""Bounded, read-only Windows network snapshot for the local desktop agent.

No router login, port scan, network reconfiguration, DNS changes, or elevated
privileges. Neighbors are only *observed cache entries*, not a complete inventory.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_OUTPUT = 22_000
_TIMEOUT_SECONDS = 20

# Fixed script with no user-controlled interpolation. No Set-*, Remove-*,
# ipconfig /flushdns, connection/disconnection, or other mutating operations.
_WINDOWS_SNAPSHOT = r"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$adapters = @(
  Get-NetAdapter -ErrorAction Stop |
    Where-Object { $_.Status -eq "Up" } |
    Select-Object -First 12 Name, Status, LinkSpeed, InterfaceDescription
)
$config = @(
  Get-NetIPConfiguration -ErrorAction Stop |
    Where-Object { $_.IPv4Address -or $_.IPv4DefaultGateway } |
    ForEach-Object {
      [pscustomobject]@{
        interface = $_.InterfaceAlias
        ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPAddress })
        gateway = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
        dns = @($_.DNSServer.ServerAddresses)
      }
    }
)
$neighbors = @(
  Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.State -in @("Reachable", "Stale", "Delay") -and
      $_.IPAddress -notmatch "^(127\.|169\.254\.|224\.|239\.|255\.)"
    } |
    Select-Object -First 40 IPAddress, InterfaceAlias, LinkLayerAddress, State
)
$profiles = @(
  Get-NetConnectionProfile -ErrorAction SilentlyContinue |
    Select-Object -First 12 InterfaceAlias, NetworkCategory, IPv4Connectivity
)
$dnsResult = "Unavailable"
try {
  $resolved = Resolve-DnsName -Name "example.com" -Type A `
    -QuickTimeout -ErrorAction Stop
  if (@($resolved | Where-Object { $_.IPAddress }).Count -gt 0) {
    $dnsResult = "OK"
  } else {
    $dnsResult = "No IPv4 result"
  }
} catch { $dnsResult = "Failed" }
$tcpResult = "Unavailable"
try {
  $socket = New-Object System.Net.Sockets.TcpClient
  try {
    $pending = $socket.BeginConnect("1.1.1.1", 443, $null, $null)
    if ($pending.AsyncWaitHandle.WaitOne(2400, $false)) {
      $socket.EndConnect($pending)
      $tcpResult = "OK"
    } else {
      $tcpResult = "Timeout"
    }
  } finally { $socket.Close() }
} catch { $tcpResult = "Failed" }

[pscustomobject]@{
  adapters = $adapters
  ip_configuration = $config
  connection_profiles = $profiles
  observed_neighbors = $neighbors
  dns_resolution = $dnsResult
  internet_tcp_443 = $tcpResult
  note = (
    "Observed neighbors are cached local devices, not a complete " +
    "router client list. LinkSpeed is not measured internet speed. " +
    "No settings were changed."
  )
} | ConvertTo-Json -Depth 8 -Compress
"""


def _windows_snapshot() -> dict[str, Any]:
    encoded = base64.b64encode(_WINDOWS_SNAPSHOT.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Windows network query failed (PowerShell exit "
            f"{completed.returncode}): {completed.stderr[:500]}"
        )
    raw = completed.stdout.strip().lstrip("\ufeff")
    if not raw:
        raise RuntimeError("Windows network query returned no output")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Network query returned invalid data")
    return parsed


@ToolRegistry.register("network_diagnostics")
class NetworkDiagnosticsTool(BaseTool):
    """Inspect local network connectivity and observed neighbors, read-only."""

    tool_id = "network_diagnostics"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="network_diagnostics",
            description=(
                "On the user's own Windows PC, READ ONLY: examine active network "
                "adapters and link speeds, local IPv4/gateway/DNS, cached "
                "neighbor devices, DNS resolution and an internet TCP probe. "
                "Use when the user asks to diagnose internet/Wi-Fi/LAN problems "
                "or find devices seen on their network. Does not optimize, "
                "change settings or enumerate every device on the router."
            ),
            parameters={"type": "object", "properties": {}},
            category="system",
            timeout_seconds=25,
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content="This read-only diagnostic currently supports Windows only.",
            )
        try:
            data = _windows_snapshot()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content=f"Network diagnostics failed: {exc}",
            )
        result = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(result) > _MAX_OUTPUT:
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content="Network snapshot exceeded the bounded output limit.",
            )
        return ToolResult(tool_name=self.tool_id, success=True, content=result)


__all__ = ["NetworkDiagnosticsTool"]
