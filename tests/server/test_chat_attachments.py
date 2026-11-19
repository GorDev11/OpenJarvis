"""Chat attachment parsing is isolated from the global knowledge store."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.upload_router import router


client = TestClient(FastAPI())
client.app.include_router(router)


def test_upload_python_file_for_chat_without_persisting(monkeypatch):
    def fail_if_called():
        raise AssertionError("Chat attachment must not open KnowledgeStore")

    monkeypatch.setattr(
        "openjarvis.server.upload_router._get_store", fail_if_called
    )
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("example.py", b"print('hello')\n", "text/plain"))],
    )
    assert response.status_code == 200
    result = response.json()["files"][0]
    assert result["name"] == "example.py"
    assert result["text"] == "print('hello')"
    assert result["truncated"] is False


def test_chat_upload_disallows_executable_binary():
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("app.exe", b"not-an-executable", "application/octet-stream"))],
    )
    assert response.status_code == 415


def test_chat_upload_truncates_long_source_file():
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("big.txt", b"A" * 9000, "text/plain"))],
    )
    assert response.status_code == 200
    file = response.json()["files"][0]
    assert len(file["text"]) == 7000
    assert file["truncated"] is True


def test_chat_upload_rejects_oversize_file():
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("big.txt", b"A" * (5 * 1024 * 1024 + 1), "text/plain"))],
    )
    assert response.status_code == 413


def test_chat_upload_rejects_more_than_four_files():
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", (f"{i}.txt", b"hello", "text/plain")) for i in range(5)],
    )
    assert response.status_code == 400
