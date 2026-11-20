"""Chat attachment parsing is isolated from the global knowledge store."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.upload_router import router

client = TestClient(FastAPI())
client.app.include_router(router)


def test_upload_python_file_for_chat_without_persisting(monkeypatch):
    def fail_if_called():
        raise AssertionError("Chat attachment must not open KnowledgeStore")

    monkeypatch.setattr("openjarvis.server.upload_router._get_store", fail_if_called)
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
        files=[
            ("files", ("app.exe", b"not-an-executable", "application/octet-stream"))
        ],
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


def test_chat_upload_accepts_png_as_image_data_without_indexing():
    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("screenshot.png", png, "image/png"))],
    )
    assert response.status_code == 200
    item = response.json()["files"][0]
    assert item["mime_type"] == "image/png"
    assert item["text"] == ""
    assert item["data_url"] == "data:image/png;base64," + base64.b64encode(png).decode()


def test_chat_upload_rejects_invalid_image_bytes():
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("screenshot.png", b"not a png", "image/png"))],
    )
    assert response.status_code == 415


def test_chat_upload_rejects_multiple_images():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[
            ("files", ("a.png", png, "image/png")),
            ("files", ("b.png", png, "image/png")),
        ],
    )
    assert response.status_code == 400


def test_chat_upload_rejects_large_images():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * (450 * 1024)
    response = client.post(
        "/v1/connectors/upload/chat-files",
        files=[("files", ("large.png", png, "image/png"))],
    )
    assert response.status_code == 413
