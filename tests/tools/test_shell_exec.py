"""Tests for the shell_exec tool's authoritative constrained runner."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from openjarvis.tools.shell_exec import ShellExecTool


def _completed(
    *, stdout: str = "", stderr: str = "", code: int = 0
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess("command", code, stdout=stdout, stderr=stderr)


class TestShellExecTool:
    def test_registered_via_tools_package_import(self):
        import openjarvis.tools as tools_pkg
        from openjarvis.core.registry import ToolRegistry

        sys.modules.pop("openjarvis.tools.shell_exec", None)
        importlib.reload(tools_pkg)

        assert ToolRegistry.contains("shell_exec")

    def test_spec(self):
        tool = ShellExecTool()
        assert tool.spec.name == "shell_exec"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 60.0
        assert "code:execute" in tool.spec.required_capabilities
        assert "command" in tool.spec.parameters["properties"]
        assert "command" in tool.spec.parameters["required"]

    def test_no_command(self):
        tool = ShellExecTool()
        result = tool.execute(command="")
        assert result.success is False
        assert "No command" in result.content

    def test_no_command_param(self):
        tool = ShellExecTool()
        result = tool.execute()
        assert result.success is False
        assert "No command" in result.content

    def test_simple_echo(self):
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed(stdout="hello\n")):
            result = tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.content
        assert "=== STDOUT ===" in result.content

    def test_capture_stderr(self):
        tool = ShellExecTool()
        with patch(
            "subprocess.run",
            return_value=_completed(stderr="error_msg\n", code=2),
        ):
            result = tool.execute(command="echo error_msg >&2")
        assert "error_msg" in result.content
        assert "=== STDERR ===" in result.content
        assert result.success is False

    def test_timeout_exceeded(self):
        tool = ShellExecTool()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("sleep 60", 1),
        ):
            result = tool.execute(command="sleep 60", timeout=1)
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_capped_at_max(self):
        """The timeout passed to the constrained runner is capped."""
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed(stdout="ok\n")) as run:
            result = tool.execute(command="echo ok", timeout=999)
        assert result.success is True
        assert result.metadata["timeout_used"] == 300
        assert run.call_args.kwargs["timeout"] == 300

    def test_working_dir(self, tmp_path):
        tool = ShellExecTool()
        with patch(
            "subprocess.run",
            return_value=_completed(stdout=str(tmp_path) + "\n"),
        ) as run:
            result = tool.execute(command="pwd", working_dir=str(tmp_path))
        assert result.success is True
        assert str(tmp_path) in result.content
        assert result.metadata["working_dir"] == str(tmp_path)
        assert run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_working_dir_not_exists(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir="/nonexistent/path")
        assert result.success is False
        assert "does not exist" in result.content

    def test_working_dir_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data", encoding="utf-8")
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir=str(f))
        assert result.success is False
        assert "not a directory" in result.content

    def test_env_clearing(self, monkeypatch):
        """Verify that arbitrary env vars are NOT passed through."""
        marker = "OPENJARVIS_TEST_SECRET_12345"
        monkeypatch.setenv(marker, "leaked")
        with patch("subprocess.run", return_value=_completed()) as run:
            result = ShellExecTool().execute(command="echo safe")
        assert result.success is True
        assert marker not in run.call_args.kwargs["env"]

    def test_env_passthrough(self, monkeypatch):
        """Verify that explicitly listed env vars ARE passed through."""
        marker = "OPENJARVIS_TEST_PASSTHROUGH_67890"
        monkeypatch.setenv(marker, "allowed_value")
        with patch("subprocess.run", return_value=_completed()) as run:
            result = ShellExecTool().execute(
                command=f"echo ${marker}",
                env_passthrough=[marker],
            )
        assert result.success is True
        assert run.call_args.kwargs["env"][marker] == "allowed_value"

    def test_returncode_in_metadata(self):
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed(stdout="ok\n")):
            result = tool.execute(command="echo ok")
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_nonzero_returncode(self):
        """A non-zero child status must never be reported as success."""
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed(stderr="bad", code=42)):
            result = tool.execute(command="exit 42")
        assert result.success is False
        assert result.metadata["returncode"] == 42
        assert "bad" in result.content

    def test_max_output_truncation(self):
        """Stdout exceeding 100 KB is truncated."""
        tool = ShellExecTool()
        with patch(
            "subprocess.run",
            return_value=_completed(stdout="A" * 200_000),
        ):
            result = tool.execute(command="large output")
        assert "truncated" in result.content
        assert len(result.content) < 200_000

    def test_no_output(self):
        """Empty stdout and stderr produce an explicit marker."""
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed()):
            result = tool.execute(command="true")
        assert result.success is True
        assert result.content == "(no output)"

    def test_tool_id(self):
        tool = ShellExecTool()
        assert tool.tool_id == "shell_exec"

    def test_to_openai_function(self):
        tool = ShellExecTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "shell_exec"
        assert "command" in fn["function"]["parameters"]["properties"]

    def test_default_timeout_metadata(self):
        tool = ShellExecTool()
        with patch("subprocess.run", return_value=_completed(stdout="ok\n")) as run:
            result = tool.execute(command="echo ok")
        assert result.metadata["timeout_used"] == 30
        assert run.call_args.kwargs["timeout"] == 30

    def test_os_exception_sets_failure(self):
        tool = ShellExecTool()
        with patch(
            "subprocess.run",
            side_effect=OSError("No such file or directory"),
        ):
            result = tool.execute(command="/nonexistent_binary")
        assert result.success is False
        assert "OS error" in result.content


class TestSanitizedEnvWindowsKeys:
    """Regression for #789: the Python fallback's env allowlist was
    POSIX-focused ("PATH", "HOME", "USER", "LANG", "TERM") and omitted
    variables Windows needs for basic process bootstrapping -- missing
    SystemRoot breaks Winsock/DNS init for any network-touching command
    (git, curl, pip, npm all fail with "getaddrinfo() thread failed to
    start"), and missing LOCALAPPDATA makes the Windows Store Python
    launcher provision a ~170MB Python\\ folder in the cwd instead of
    finding the real interpreter.
    """

    def test_base_env_keys_include_windows_essentials(self):
        from openjarvis.tools.shell_exec import _WINDOWS_ENV_KEYS

        for key in (
            "SystemRoot",
            "SystemDrive",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        ):
            assert key in _WINDOWS_ENV_KEYS, f"{key} missing from Windows keys"

    def test_windows_keys_are_only_enabled_on_windows(self):
        from openjarvis.tools.shell_exec import _BASE_ENV_KEYS, _WINDOWS_ENV_KEYS

        if os.name == "nt":
            assert set(_WINDOWS_ENV_KEYS) <= set(_BASE_ENV_KEYS)
        else:
            assert set(_WINDOWS_ENV_KEYS).isdisjoint(_BASE_ENV_KEYS)

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_windows_env_vars_reach_the_subprocess(self, monkeypatch):
        """Windows-critical variables reach the constrained child env."""
        monkeypatch.setenv("SystemRoot", r"C:\Windows")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")

        captured: dict = {}

        def _fake_run(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

        tool = ShellExecTool()
        with patch("subprocess.run", side_effect=_fake_run):
            result = tool.execute(command="echo ok")

        assert result.success is True
        env = captured["env"]
        assert env is not None
        assert env.get("SystemRoot") == r"C:\Windows"
        assert env.get("LOCALAPPDATA") == r"C:\Users\tester\AppData\Local"

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_real_windows_child_bootstraps_and_resolves_localhost(
        self, tmp_path, monkeypatch
    ):
        """Exercise the actual sanitized environment and Windows process path."""
        import json

        local_app_data = str(tmp_path / "LocalAppData")
        monkeypatch.setenv("LOCALAPPDATA", local_app_data)
        probe = (
            "import json, os, socket; "
            "addresses = socket.getaddrinfo('localhost', 80); "
            "print(json.dumps({"
            "'SystemRoot': os.environ.get('SystemRoot'), "
            "'LOCALAPPDATA': os.environ.get('LOCALAPPDATA'), "
            "'dns_ok': bool(addresses)}))"
        )
        command = subprocess.list2cmdline([sys.executable, "-c", probe])

        result = ShellExecTool().execute(command=command)

        assert result.success is True, result.content
        stdout = result.content.split("=== STDOUT ===\n", 1)[1].splitlines()[0]
        payload = json.loads(stdout)
        assert payload["SystemRoot"] == os.environ["SystemRoot"]
        assert payload["LOCALAPPDATA"] == local_app_data
        assert payload["dns_ok"] is True
