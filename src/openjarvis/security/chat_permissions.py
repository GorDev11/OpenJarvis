"""Live, fail-closed tool permission broker for the trusted Desktop Chat.

Unlike proactive approval_store, this queue resumes the *actual suspended tool
call* and only a click on the matching request can release it. Requests expire
without being executed. Never place API keys or complete tool results here.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from openjarvis.core.paths import get_config_dir
from openjarvis.security.confirmation import is_desktop_runtime

MODES = ("autonomous", "guided")
DEFAULT_MODE = "autonomous"
TIMEOUT_SECONDS = 120
MAX_PENDING = 16
_PREVIEW_LIMIT = 4000
_SENSITIVE = re.compile(
    r"(?:shell|exec|command|write|delete|remove|send|post|put|patch|"
    r"update|create|modify|install|uninstall|publish|payment|transfer|"
    r"browser_click|browser_type|http_request|git_push|git_commit)",
    re.IGNORECASE,
)
# Unknown tools are not silently treated as read-only. A tight allowlist
# means new integrations need an explicit security review before auto-use.
_READ_ONLY = frozenset({
    "web_search", "browser_navigate", "browser_read", "file_read",
    "knowledge_search", "calculator", "memory_search", "web_fetch",
    "search_files", "list_files", "get_weather", "read_url",
    "browser_snapshot", "time", "get_current_time", "read_email",
    "gmail_search", "gmail_read", "calendar_list", "contacts_search",
})


def mode_path() -> Path:
    return get_config_dir() / "chat_permissions.json"


def get_mode() -> str:
    try:
        data = json.loads(mode_path().read_text(encoding="utf-8"))
        value = data.get("mode")
        return value if value in MODES else DEFAULT_MODE
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_MODE


def set_mode(value: str) -> str:
    if value not in MODES:
        raise ValueError("Unknown permission mode")
    target = mode_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic settings update; never persist a blanket 'allow all' token.
    import os

    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps({"mode": value}), encoding="utf-8")
    os.replace(temp, target)
    return value


def requires_chat_approval(tool_name: str, dangerous: bool) -> bool:
    """Enforce a security floor even when a ToolSpec forgot to flag a writer."""
    if not is_desktop_runtime():
        return dangerous
    if dangerous or _SENSITIVE.search(tool_name):
        return True
    if get_mode() == "guided":
        return True
    return tool_name not in _READ_ONLY


@dataclass
class Request:
    id: str
    prompt: str
    tool: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: bool = False

    def public(self) -> dict[str, str]:
        return {"id": self.id, "prompt": self.prompt, "tool": self.tool}


class ChatPermissionBroker:
    """Thread-safe in-memory live queue; no replayable persistent approvals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, Request] = {}

    def request(self, prompt: str, timeout: float = TIMEOUT_SECONDS) -> bool:
        if not is_desktop_runtime():
            return False
        # The tool name originates inside the ToolExecutor's *formatted* gate.
        name_match = re.search(r"tool '([^']+)'", prompt)
        name = name_match.group(1) if name_match else "tool"
        item = Request(id=uuid.uuid4().hex, tool=name, prompt=prompt[:_PREVIEW_LIMIT])
        with self._lock:
            if len(self._pending) >= MAX_PENDING:
                return False
            self._pending[item.id] = item
        try:
            if not item.event.wait(timeout):
                return False
            return item.answer
        finally:
            with self._lock:
                self._pending.pop(item.id, None)

    def pending(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                req.public()
                for req in self._pending.values()
                if not req.event.is_set()
            ]

    def decide(self, request_id: str, allow: bool) -> bool:
        with self._lock:
            item = self._pending.get(request_id)
            if item is None or item.event.is_set():
                return False
            item.answer = allow
            item.event.set()
            return True


broker = ChatPermissionBroker()


def chat_tool_confirmation(prompt: str) -> bool:
    """Synchronous ToolExecutor callback; waits on a worker, never the loop."""
    return broker.request(str(prompt))


__all__ = [
    "broker", "get_mode", "set_mode", "requires_chat_approval",
    "chat_tool_confirmation", "ChatPermissionBroker",
]
