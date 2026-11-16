"""Fail-closed confirmation helpers for sensitive Desktop tool calls."""

from __future__ import annotations

import os
import sys

_DESKTOP_ENV = "OPENJARVIS_DESKTOP"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_desktop_runtime() -> bool:
    """Return whether this backend was started by the trusted Desktop shell."""

    return os.environ.get(_DESKTOP_ENV, "").strip().lower() in _TRUTHY


def _show_windows_confirmation(prompt: str) -> bool:
    """Show one native Windows Yes/No prompt; every failure means denial."""

    try:
        import ctypes

        # MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2 (No) |
        # MB_SETFOREGROUND | MB_TOPMOST
        flags = 0x00000004 | 0x00000030 | 0x00000100 | 0x00010000 | 0x00040000
        answer = ctypes.windll.user32.MessageBoxW(
            None,
            (
                "OpenJarvis requests a sensitive action:\n\n"
                f"{prompt[:12_000]}\n\n"
                "Review the exact tool arguments above. Allow this action?"
            ),
            "OpenJarvis - Confirm tool execution",
            flags,
        )
    except Exception:
        return False
    return answer == 6  # IDYES; No, close, and errors deny.


def desktop_tool_confirmation(prompt: str) -> bool:
    """Ask the local Desktop user to approve one sensitive tool invocation.

    Browser/headless/server deployments never gain approval merely because
    they run on Windows.  The Tauri launcher must explicitly mark its child
    backend with ``OPENJARVIS_DESKTOP=1``.  This prevents remote API callers
    and scheduled processes from silently inheriting an allow-all callback.
    """

    if not is_desktop_runtime() or sys.platform != "win32":
        return False
    return _show_windows_confirmation(str(prompt))


__all__ = ["desktop_tool_confirmation", "is_desktop_runtime"]
