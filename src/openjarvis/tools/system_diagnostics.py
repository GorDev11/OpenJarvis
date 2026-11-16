"""Bounded, read-only Windows hardware and operating-system diagnostics."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_MAX_OUTPUT = 65_536
_TIMEOUT_SECONDS = 35

# This script has no user-controlled interpolation and contains inspection
# commands only. It intentionally avoids Set-*, Remove-*, Stop-*, Start-*,
# package managers, registry writes, service changes, and event-log clearing.
_WINDOWS_SYSTEM_SNAPSHOT = r"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Read-Section([scriptblock]$Script) {
  try { & $Script }
  catch { [pscustomobject]@{ error = $_.Exception.Message } }
}

$os = Read-Section {
  $item = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  [pscustomobject]@{
    caption = $item.Caption
    version = $item.Version
    build = $item.BuildNumber
    last_boot = $item.LastBootUpTime
    total_memory_bytes = [int64]$item.TotalVisibleMemorySize * 1KB
    free_memory_bytes = [int64]$item.FreePhysicalMemory * 1KB
  }
}

$cpu = Read-Section {
  @(
    Get-CimInstance Win32_Processor -ErrorAction Stop |
      Select-Object -First 4 Name, LoadPercentage, NumberOfCores,
        NumberOfLogicalProcessors, MaxClockSpeed
  )
}

$gpu = Read-Section {
  @(
    Get-CimInstance Win32_VideoController -ErrorAction Stop |
      Select-Object -First 8 Name, DriverVersion, AdapterRAM,
        CurrentHorizontalResolution, CurrentVerticalResolution
  )
}

$nvidia = Read-Section {
  if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
    $gpuQuery = "name,driver_version,temperature.gpu," +
      "utilization.gpu,memory.total,memory.used"
    @(
      & nvidia-smi.exe `
        "--query-gpu=$gpuQuery" `
        --format=csv,noheader,nounits 2>$null |
        Select-Object -First 8
    )
  } else { @() }
}

$disks = Read-Section {
  @(
    Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop |
      Select-Object -First 24 DeviceID, VolumeName, FileSystem, Size, FreeSpace
  )
}

$processes = Read-Section {
  @(
    Get-Process -ErrorAction Stop |
      Sort-Object WorkingSet64 -Descending |
      Select-Object -First 20 Id, ProcessName, CPU, WorkingSet64,
        PrivateMemorySize64, StartTime
  )
}

$services = Read-Section {
  $all = @(Get-CimInstance Win32_Service -ErrorAction Stop)
  [pscustomobject]@{
    total = $all.Count
    running = @($all | Where-Object { $_.State -eq "Running" }).Count
    stopped_automatic = @(
      $all |
        Where-Object {
          $_.StartMode -eq "Auto" -and $_.State -ne "Running" -and
          $_.Name -notin @("MapsBroker", "sppsvc", "WbioSrvc")
        } |
        Select-Object -First 30 Name, DisplayName, State, StartMode, ExitCode
    )
  }
}

$installed = Read-Section {
  $paths = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )
  @(
    Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName } |
      Sort-Object DisplayName -Unique |
      Select-Object -First 100 DisplayName, DisplayVersion, Publisher, InstallDate
  )
}

$recentErrors = Read-Section {
  @(
    Get-WinEvent -FilterHashtable @{
      LogName = "System"
      Level = 1, 2
      StartTime = (Get-Date).AddHours(-24)
    } -MaxEvents 20 -ErrorAction SilentlyContinue |
      ForEach-Object {
        [pscustomobject]@{
          time_created = $_.TimeCreated
          provider = $_.ProviderName
          event_id = $_.Id
          level = $_.LevelDisplayName
          message = if ($_.Message) {
            $_.Message.Substring(0, [Math]::Min(700, $_.Message.Length))
          } else {
            ""
          }
        }
      }
  )
}

[pscustomobject]@{
  operating_system = $os
  cpu = $cpu
  gpu = $gpu
  nvidia_gpu_samples = $nvidia
  fixed_disks = $disks
  top_processes_by_working_set = $processes
  services = $services
  installed_programs = $installed
  recent_system_errors_24h = $recentErrors
  note = (
    "Read-only snapshot. CPU load is a point-in-time WMI value; process CPU " +
    "is cumulative seconds, not current percent. Event-log errors may be " +
    "historical and do not by themselves prove an active fault. No settings changed."
  )
} | ConvertTo-Json -Depth 8 -Compress
"""


def _windows_system_snapshot() -> dict[str, Any]:
    encoded = base64.b64encode(_WINDOWS_SYSTEM_SNAPSHOT.encode("utf-16-le")).decode(
        "ascii"
    )
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
            "Windows system query failed (PowerShell exit "
            f"{completed.returncode}): {completed.stderr[:500]}"
        )
    raw = completed.stdout.strip().lstrip("\ufeff")
    if not raw:
        raise RuntimeError("Windows system query returned no output")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("System query returned invalid data")
    return parsed


@ToolRegistry.register("system_diagnostics")
class SystemDiagnosticsTool(BaseTool):
    """Inspect local Windows health and inventory without changing it."""

    tool_id = "system_diagnostics"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "On the user's own Windows PC, READ ONLY: inspect OS and boot "
                "information, CPU/RAM/GPU, fixed disks, high-memory processes, "
                "service state, installed programs, and recent critical/error "
                "System events. Use for explicit computer-health or Windows "
                "diagnostic requests. Does not change, stop, install, or delete "
                "anything."
            ),
            parameters={"type": "object", "properties": {}},
            category="system",
            timeout_seconds=40,
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content="This read-only diagnostic currently supports Windows only.",
            )
        try:
            data = _windows_system_snapshot()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content=f"System diagnostics failed: {exc}",
            )
        result = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(result) > _MAX_OUTPUT:
            return ToolResult(
                tool_name=self.tool_id,
                success=False,
                content="System snapshot exceeded the bounded output limit.",
            )
        return ToolResult(tool_name=self.tool_id, success=True, content=result)


__all__ = ["SystemDiagnosticsTool"]
