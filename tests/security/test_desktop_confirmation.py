"""Desktop confirmation must never fail open."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.security.confirmation import (
    desktop_tool_confirmation,
    is_desktop_runtime,
)


def test_desktop_marker_is_explicit(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OPENJARVIS_DESKTOP", raising=False)
    assert is_desktop_runtime() is False

    monkeypatch.setenv("OPENJARVIS_DESKTOP", "true")
    assert is_desktop_runtime() is True


def test_confirmation_denies_headless_windows(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("OPENJARVIS_DESKTOP", raising=False)
    with (
        patch("openjarvis.security.confirmation.sys.platform", "win32"),
        patch("openjarvis.security.confirmation._show_windows_confirmation") as show,
    ):
        assert desktop_tool_confirmation("run shell") is False
    show.assert_not_called()


def test_confirmation_denies_non_windows_desktop(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("OPENJARVIS_DESKTOP", "1")
    with (
        patch("openjarvis.security.confirmation.sys.platform", "linux"),
        patch("openjarvis.security.confirmation._show_windows_confirmation") as show,
    ):
        assert desktop_tool_confirmation("run shell") is False
    show.assert_not_called()


def test_confirmation_forwards_each_windows_desktop_prompt(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("OPENJARVIS_DESKTOP", "1")
    with (
        patch("openjarvis.security.confirmation.sys.platform", "win32"),
        patch(
            "openjarvis.security.confirmation._show_windows_confirmation",
            side_effect=[True, False],
        ) as show,
    ):
        assert desktop_tool_confirmation("command one") is True
        assert desktop_tool_confirmation("command two") is False

    assert [call.args[0] for call in show.call_args_list] == [
        "command one",
        "command two",
    ]
