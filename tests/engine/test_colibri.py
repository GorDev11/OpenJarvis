"""Colibri integration contract: pinned official installer and engine registration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest
import respx

from openjarvis.core.config import EngineConfig
from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import ColibriEngine


def test_colibri_registry_and_config() -> None:
    EngineRegistry.register_value("colibri", ColibriEngine)
    assert EngineRegistry.get("colibri") is ColibriEngine
    assert EngineConfig().colibri.host == "http://127.0.0.1:19000"


def test_colibri_recognizes_openai_compatible_models() -> None:
    engine = ColibriEngine(host="http://127.0.0.1:19000")
    with respx.mock:
        respx.get("http://127.0.0.1:19000/v1/models").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "qwen36-35b-local"}]}
            )
        )
        assert engine.list_models() == ["qwen36-35b-local"]


def test_colibri_tool_failure_never_falls_back_to_no_tools() -> None:
    engine = ColibriEngine(host="http://127.0.0.1:19000")
    with respx.mock:
        route = respx.post("http://127.0.0.1:19000/v1/chat/completions").mock(
            return_value=httpx.Response(400, text="unsupported tool schema")
        )
        with pytest.raises(EngineConnectionError, match="HTTP 400"):
            engine.generate(
                [Message(role=Role.USER, content="Use calculator")],
                model="qwen36-35b-local",
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }],
            )
        assert route.call_count == 1


def test_pinned_installer_does_not_use_remote_shell_pipe() -> None:
    path = Path(__file__).parents[2] / "scripts" / "setup_colibri_qwen36.py"
    spec = importlib.util.spec_from_file_location("colibri_setup_script", path)
    assert spec is not None and spec.loader is not None
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    assert setup.MODEL == "qwen36-35b"
    assert setup.PORT == 19000
    assert setup.accepted_origin("https://github.com/JustVugg/colibri.git")
    assert not setup.accepted_origin("https://github.com/other/colibri.git")
    assert len(setup.PINNED_COMMIT) == 40
