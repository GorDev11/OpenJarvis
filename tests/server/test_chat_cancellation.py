"""Regression tests for explicit desktop cancellation of an agent stream."""

from __future__ import annotations

import asyncio
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
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {
        "status": "cancelling"
    }
    bridge.cancel.assert_called_once_with()
    app.state.chat_cancellations.unregister(request_id, bridge)
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {
        "status": "not_found"
    }


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
    assert client.post(f"/v1/chat/cancel/{request_id}").json() == {
        "status": "cancelling"
    }
    first.cancel.assert_called_once_with()
    second.cancel.assert_not_called()


def test_cancel_before_stream_registration_is_not_lost():
    registry = ChatCancellationRegistry()
    request_id = str(uuid.uuid4())
    assert registry.cancel(request_id) == "pending"
    bridge = MagicMock()
    assert registry.register(request_id, bridge)
    bridge.cancel.assert_called_once_with()
    registry.unregister(request_id, bridge)
    assert registry.cancel(request_id) == "not_found"


def test_early_stop_endpoint_acknowledges_pending_cancellation():
    app = FastAPI()
    app.state.chat_cancellations = ChatCancellationRegistry()
    app.include_router(router)
    request_id = str(uuid.uuid4())
    with TestClient(app) as client:
        response = client.post(f"/v1/chat/cancel/{request_id}")
        assert response.status_code == 200
        assert response.json() == {"status": "pending"}
    bridge = MagicMock()
    assert app.state.chat_cancellations.register(request_id, bridge)
    bridge.cancel.assert_called_once_with()


def test_cancelled_stream_wakes_without_waiting_for_agent_output():
    from openjarvis.core.events import EventBus
    from openjarvis.server.models import ChatCompletionRequest
    from openjarvis.server.stream_bridge import AgentStreamBridge

    async def exercise():
        def blocked_runner(_callback, cancel_event):
            cancel_event.wait(timeout=3)
            raise RuntimeError("cancelled")

        request = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "Hello"}],
            stream=True,
        )
        bridge = AgentStreamBridge(
            MagicMock(),
            EventBus(),
            "test-model",
            request,
            runner=blocked_runner,
        )
        stream = bridge.stream()
        try:
            first = await anext(stream)
            assert "chat.completion.chunk" in first
            reading = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            bridge.cancel()
            try:
                await asyncio.wait_for(reading, timeout=1.0)
            except StopAsyncIteration:
                pass
            else:
                raise AssertionError("Cancelled SSE stream did not exit")
        finally:
            await stream.aclose()

    asyncio.run(exercise())
