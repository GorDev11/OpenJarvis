"""Regression tests for explicit desktop cancellation of an agent stream."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.routes import ChatCancellationRegistry, router


def test_cancel_endpoint_signals_registered_agent():
    app = FastAPI()
    app.state.chat_cancellations = ChatCancellationRegistry()
    app.include_router(router)
    client = TestClient(app)
    request_id = str(uuid.uuid4())
    bridge = MagicMock()
    assert app.state.chat_cancellations.register(request_id, bridge)
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {"status": "cancelling"}
    bridge.cancel.assert_called_once_with()
    app.state.chat_cancellations.unregister(request_id, bridge)
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {"status": "not_found"}


def test_invalid_duplicate_and_foreign_cancellation():
    app = FastAPI()
    app.state.chat_cancellations = ChatCancellationRegistry()
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/v1/chat/cancel/not-a-uuid").status_code == 400
    request_id = str(uuid.uuid4())
    first, second = MagicMock(), MagicMock()
    registry = app.state.chat_cancellations
    assert registry.register(request_id, first)
    assert not registry.register(request_id, second)
    registry.unregister(request_id, second)
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {"status": "cancelling"}
    first.cancel.assert_called_once_with()
    second.cancel.assert_not_called()
