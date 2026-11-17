"""Live desktop Chat permission tests; no shell or network side effects."""

from __future__ import annotations

import threading

from openjarvis.security import chat_permissions as permissions


def test_non_desktop_cannot_request_or_approve(monkeypatch) -> None:
    monkeypatch.delenv("OPENJARVIS_DESKTOP", raising=False)
    broker = permissions.ChatPermissionBroker()
    assert broker.request("Allow execution of tool 'shell_exec'?") is False
    assert broker.pending() == []


def test_request_resumes_exact_call_after_yes(monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_DESKTOP", "1")
    broker = permissions.ChatPermissionBroker()
    outcomes: list[bool] = []
    thread = threading.Thread(
        target=lambda: outcomes.append(
            broker.request("Allow execution of tool 'shell_exec'?", 2)
        )
    )
    thread.start()
    try:
        import time

        for _ in range(100):
            pending = broker.pending()
            if pending:
                break
            time.sleep(0.005)
        assert len(pending) == 1
        assert pending[0]["tool"] == "shell_exec"
        assert not broker.decide("unknown", True)
        assert broker.decide(pending[0]["id"], True)
        assert not broker.decide(pending[0]["id"], True)
    finally:
        thread.join(timeout=3)
    assert outcomes == [True]
    assert broker.pending() == []


def test_denial_and_timeout_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_DESKTOP", "1")
    broker = permissions.ChatPermissionBroker()
    assert broker.request("shell_exec", timeout=0.001) is False
    assert broker.pending() == []


def test_autonomous_reads_only_and_guided_asks_all(monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_DESKTOP", "1")
    monkeypatch.setattr(permissions, "get_mode", lambda: "autonomous")
    assert not permissions.requires_chat_approval("web_search", False)
    assert permissions.requires_chat_approval("shell_exec", True)
    assert permissions.requires_chat_approval("gmail_send", False)
    assert permissions.requires_chat_approval("unknown_plugin", False)
    monkeypatch.setattr(permissions, "get_mode", lambda: "guided")
    assert permissions.requires_chat_approval("web_search", False)
