"""Unit tests for the opt-in Armenian Pocket-TTS backend (no model downloads)."""

from __future__ import annotations

import sys
import types

import pytest

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.armenian_pocket_tts import ArmenianPocketTTSBackend


def test_registered():
    assert TTSRegistry.contains("armenian_pocket")


def test_health_is_false_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "OPENJARVIS_ARMENIAN_TTS_CONFIG", str(tmp_path / "absent.yaml")
    )
    assert ArmenianPocketTTSBackend().health() is False


def test_voice_catalog_and_validation():
    backend = ArmenianPocketTTSBackend()
    assert backend.available_voices() == ["hy-default"]
    with pytest.raises(ValueError, match="speed=1.0"):
        backend.synthesize("Բարև", speed=1.2)
    with pytest.raises(ValueError, match="WAV only"):
        backend.synthesize("Բարև", output_format="mp3")
    with pytest.raises(ValueError, match="Unsupported"):
        backend.synthesize("Բարև", voice_id="bm_george")


def test_synthesize_with_fake_model(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("soundfile")

    config = tmp_path / "config_armenian.yaml"
    config.write_text("test: yes\n", encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_CONFIG", str(config))

    calls = []

    class FakeTensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return np.asarray([0.0, 0.1, -0.1, 0.0], dtype=np.float32)

    class FakeModel:
        sample_rate = 24000

        def get_state_for_audio_prompt(self, prompt):
            calls.append(("prompt", prompt))
            return "voice"

        def generate_audio(self, voice, text):
            calls.append(("generate", voice, text))
            return FakeTensor()

    class FakeTTSModel:
        @staticmethod
        def load_model(config):
            calls.append(("load", config))
            return FakeModel()

    fake_package = types.ModuleType("pocket_tts")
    fake_package.TTSModel = FakeTTSModel
    monkeypatch.setitem(sys.modules, "pocket_tts", fake_package)

    backend = ArmenianPocketTTSBackend()
    one = backend.synthesize("Բարև")
    two = backend.synthesize("Եվս մեկ նախադասություն")

    assert one.audio.startswith(b"RIFF")
    assert one.sample_rate == 24000
    assert one.voice_id == "hy-default"
    assert two.audio.startswith(b"RIFF")
    assert [c[0] for c in calls].count("load") == 1
    assert [c[0] for c in calls].count("prompt") == 1
    assert [c[0] for c in calls].count("generate") == 2
