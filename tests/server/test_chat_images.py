"""Chat API vision payload contracts without an inference server."""

from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from openjarvis.core.types import Message, Role
from openjarvis.engine._openai_compat import _openai_messages_with_images
from openjarvis.server.models import ChatMessage
from openjarvis.server.routes import _to_messages


def test_chat_image_is_forwarded_to_core_messages():
    raw = b"\xff\xd8\xff" + b"abc"
    url = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    messages = _to_messages(
        [ChatMessage(role="user", content="Describe image", images=[url])]
    )
    assert messages[0].images == [base64.b64encode(raw).decode()]


def test_compat_engine_emits_openai_image_url():
    b64 = base64.b64encode(b"\xff\xd8\xff" + b"abc").decode()
    messages = _openai_messages_with_images(
        [Message(role=Role.USER, content="Describe image", images=[b64])]
    )
    assert messages[0]["content"][0] == {"type": "text", "text": "Describe image"}
    assert (
        messages[0]["content"][1]["image_url"]["url"]
        == "data:image/jpeg;base64," + b64
    )
    assert "images" not in messages[0]


def test_compat_engine_text_only_stays_unchanged():
    assert _openai_messages_with_images([Message(role=Role.USER, content="hello")]) == [
        {"role": "user", "content": "hello"}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,not-base64",
        "data:image/jpeg;base64," + base64.b64encode(b"not jpeg").decode(),
        "https://example.com/pic.png",
    ],
)
def test_invalid_or_external_image_is_rejected(url):
    with pytest.raises(HTTPException):
        _to_messages([ChatMessage(role="user", images=[url])])
