"""Regression tests for telemetry wiring in ``jarvis serve``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from openjarvis.cli.serve import _instrument_server_engine
from openjarvis.core.events import EventBus
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine


def _config(*, enabled: bool, gpu_metrics: bool):
    return SimpleNamespace(
        telemetry=SimpleNamespace(
            enabled=enabled,
            gpu_metrics=gpu_metrics,
            gpu_poll_interval_ms=750,
            energy_vendor="nvidia",
            allow_energy_estimates=False,
        )
    )


def test_disabled_telemetry_does_not_wrap_server_engine():
    engine = MagicMock()

    result = _instrument_server_engine(
        engine,
        _config(enabled=False, gpu_metrics=False),
        EventBus(),
        MagicMock(),
    )

    assert result is engine


def test_gpu_metrics_false_keeps_request_telemetry_without_energy_polling():
    engine = MagicMock()

    result = _instrument_server_engine(
        engine,
        _config(enabled=True, gpu_metrics=False),
        EventBus(),
        MagicMock(),
    )

    assert isinstance(result, InstrumentedEngine)
    assert result._inner is engine
    assert result._energy_monitor is None


def test_gpu_metrics_true_uses_configured_monitor_settings(monkeypatch):
    engine = MagicMock()
    monitor = MagicMock()
    monitor.vendor.return_value.value = "nvidia"
    monitor.energy_method.return_value = "hw_counter"
    create = MagicMock(return_value=monitor)
    monkeypatch.setattr(
        "openjarvis.telemetry.energy_monitor.create_energy_monitor",
        create,
    )

    result = _instrument_server_engine(
        engine,
        _config(enabled=True, gpu_metrics=True),
        EventBus(),
        MagicMock(),
    )

    assert isinstance(result, InstrumentedEngine)
    assert result._energy_monitor is monitor
    create.assert_called_once_with(
        poll_interval_ms=750,
        prefer_vendor="nvidia",
        allow_estimates=False,
    )
