"""Tests for complete Ollama runtime sampler option wiring."""

from __future__ import annotations

from openjarvis.engine.ollama import _ollama_request_options


def test_with_explicit_runtime_kwargs() -> None:
    opts = _ollama_request_options(
        temperature=0.5,
        max_tokens=512,
        kwargs={"num_ctx": 64000, "num_gpu": 12},
    )
    assert opts["num_ctx"] == 64000
    assert opts["num_gpu"] == 12


def test_default_num_ctx_when_omitted(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("JARVIS_NUM_CTX", "24576")
    opts = _ollama_request_options(
        temperature=0.7,
        max_tokens=1024,
        kwargs={},
    )
    assert opts["num_ctx"] == 24576
    assert "num_gpu" not in opts


def test_provider_neutral_sampler_options_reach_ollama() -> None:
    opts = _ollama_request_options(
        temperature=0.4,
        max_tokens=256,
        kwargs={
            "top_p": 0.82,
            "top_k": 31,
            "min_p": 0.08,
            "seed": 7,
            "repetition_penalty": 1.17,
            "repeat_last_n": 96,
            "stop": ["END"],
        },
    )

    assert opts == {
        "temperature": 0.4,
        "num_predict": 256,
        "num_ctx": 16384,
        "top_p": 0.82,
        "top_k": 31,
        "min_p": 0.08,
        "seed": 7,
        "repeat_penalty": 1.17,
        "repeat_last_n": 96,
        "stop": ["END"],
    }


def test_native_repeat_penalty_takes_precedence() -> None:
    opts = _ollama_request_options(
        temperature=0.7,
        max_tokens=128,
        kwargs={"repeat_penalty": 1.3, "repetition_penalty": 1.1},
    )
    assert opts["repeat_penalty"] == 1.3
