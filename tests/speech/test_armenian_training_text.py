"""Tests for revision-pinned Pocket-TTS training text normalization."""

from __future__ import annotations

import sys
import types

from openjarvis.speech import armenian_training_text as training


def test_can_disable_normalization_without_network(monkeypatch):
    monkeypatch.setenv("OPENJARVIS_ARMENIAN_TTS_TRAINING_NORMALIZE", "0")

    def fail_loader():
        raise AssertionError("must not import/download the author rules")

    monkeypatch.setattr(training, "_load_training_normaliser", fail_loader)
    assert training.normalize_for_pocket_training("Բարև, ChatGPT։") == (
        "Բարև, ChatGPT։"
    )


def test_author_normalise_is_called(monkeypatch):
    monkeypatch.delenv("OPENJARVIS_ARMENIAN_TTS_TRAINING_NORMALIZE", raising=False)
    monkeypatch.setattr(
        training, "_load_training_normaliser", lambda: lambda t: t + "!"
    )
    assert training.normalize_for_pocket_training("Բարև") == "Բարև!"
    assert training.normalize_for_pocket_training("   ") == "   "


def test_pinned_files_are_downloaded_together_and_loaded(tmp_path, monkeypatch):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "hy_itn.py").write_text(
        "def digits_to_words(s):\n"
        "    return s.replace('123', 'հարյուր քսաներեք')\n",
        encoding="utf-8",
    )
    (configs / "hy_text.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.dirname(__file__))\n"
        "from hy_itn import digits_to_words\n"
        "def normalise(text):\n"
        "    return digits_to_words(text).replace('։', '.')\n",
        encoding="utf-8",
    )

    calls = []

    def fake_download(*, repo_id, filename, revision):
        calls.append((repo_id, filename, revision))
        return str(tmp_path / filename)

    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)

    training._load_training_normaliser.cache_clear()
    try:
        normalise = training._load_training_normaliser()
        assert normalise("Գինը 123 դրամ է։") == (
            "Գինը հարյուր քսաներեք դրամ է."
        )
        assert [c[1] for c in calls] == [
            "configs/hy_itn.py",
            "configs/hy_text.py",
        ]
        assert all(c[0] == training._REPO for c in calls)
        assert all(c[2] == training._REVISION for c in calls)
    finally:
        training._load_training_normaliser.cache_clear()
