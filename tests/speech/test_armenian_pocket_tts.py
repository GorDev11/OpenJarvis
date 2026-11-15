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


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_synthesize_with_fake_model(tmp_path, monkeypatch, device):
    np = pytest.importorskip("numpy")
    pytest.importorskip("soundfile")

    config = tmp_path / "config_armenian.yaml"
    config.write_text("test: yes\n", encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_CONFIG", str(config))
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_DEVICE", device)
    # Network-free model mock; training text rules are verified separately.
    monkeypatch.setattr(
        "openjarvis.speech.armenian_pocket_tts.normalize_for_pocket_training",
        lambda text: text.replace("Ասա", "Արտասանիր"),
    )

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: device == "cuda")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

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

        def to(self, target):
            calls.append(("to", target))
            return self

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
    mixed = backend.synthesize("Ասա ChatGPT կամ Gemini և AI։")

    assert one.audio.startswith(b"RIFF")
    assert one.sample_rate == 24000
    assert one.voice_id == "hy-default"
    assert two.audio.startswith(b"RIFF")
    assert [c[0] for c in calls].count("load") == 1
    assert [c[0] for c in calls].count("prompt") == 1
    assert mixed.audio.startswith(b"RIFF")
    assert [c[0] for c in calls].count("generate") == 3
    assert ("generate", "voice", "Արտասանիր Չաթ Ջի Փի Թի կամ Ջեմինի և Էյ Այ։") in calls
    assert backend._device == device
    assert [c for c in calls if c[0] == "to"] == (
        [("to", "cuda")] if device == "cuda" else []
    )


def test_variant_selection_builds_separate_run5_config(tmp_path, monkeypatch):
    yaml = pytest.importorskip("yaml")
    model_yaml = tmp_path / "original.yaml"
    original = {
        "weights_path": "run4_original.safetensors",
        "flow_lm": {
            "lookup_table": {
                "tokenizer": "sentencepiece",
                "tokenizer_path": "run4_original.model",
            }
        },
    }
    model_yaml.write_text(yaml.safe_dump(original), encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_CONFIG", str(model_yaml))
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_VARIANT", "run5_175k")
    monkeypatch.setattr(
        "openjarvis.speech.armenian_pocket_tts.Path.home",
        lambda: tmp_path,
    )

    calls = []

    def fake_download(*, repo_id, filename, revision):
        calls.append(filename)
        return str(tmp_path / filename)

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    backend = ArmenianPocketTTSBackend()
    derived = backend._model_config_for_variant()
    assert derived.exists()
    assert derived != model_yaml
    assert yaml.safe_load(model_yaml.read_text(encoding="utf-8")) == original
    cfg = yaml.safe_load(derived.read_text(encoding="utf-8"))
    assert cfg["weights_path"].endswith("run5_175k/model.safetensors")
    assert cfg["flow_lm"]["lookup_table"]["tokenizer_path"].endswith(
        "run5_175k/tokenizer_hy5.model"
    )
    assert calls == [
        "run5_175k/model.safetensors",
        "run5_175k/tokenizer_hy5.model",
    ]


def test_unknown_variant_is_rejected(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("test: true\n", encoding="utf-8")
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_CONFIG", str(config))
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_VARIANT", "unknown")
    with pytest.raises(ValueError, match="VARIANT"):
        ArmenianPocketTTSBackend()._model_config_for_variant()
