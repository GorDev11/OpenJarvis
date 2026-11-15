"""Optional local Eastern Armenian Pocket-TTS backend.

Set OPENJARVIS_ARMENIAN_TTS_CONFIG to a previously tested Pocket-TTS YAML,
or keep the default file at ~/OpenJarvis-Armenian-TTS/config_armenian.yaml.
The model loads lazily on first speech synthesis, and is then reused.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import os
import threading
from pathlib import Path
from typing import Any, List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.armenian_audio import shorten_long_pauses
from openjarvis.speech.armenian_pronunciation import normalize_armenian_speech
from openjarvis.speech.armenian_training_text import normalize_for_pocket_training
from openjarvis.speech.tts import TTSBackend, TTSResult

_DEFAULT_PROMPT = "hf://kyutai/tts-voices/alba-mackenna/casual.wav"
_VOICE_ID = "hy-default"


@TTSRegistry.register("armenian_pocket")
class ArmenianPocketTTSBackend(TTSBackend):
    """Speak Armenian with a locally installed Pocket-TTS model."""

    backend_id = "armenian_pocket"

    def __init__(self) -> None:
        default_config = Path.home() / "OpenJarvis-Armenian-TTS" / "config_armenian.yaml"
        self._config_path = Path(
            os.environ.get("OPENJARVIS_ARMENIAN_TTS_CONFIG") or str(default_config)
        ).expanduser()
        self._voice_prompt = os.environ.get(
            "OPENJARVIS_ARMENIAN_TTS_VOICE_PROMPT", _DEFAULT_PROMPT
        )
        self._variant = os.environ.get(
            "OPENJARVIS_ARMENIAN_TTS_VARIANT", "run4_60k"
        ).strip().lower()
        self._trim_pauses = os.environ.get(
            "OPENJARVIS_ARMENIAN_TTS_TRIM_PAUSES", "1"
        ).strip().lower() not in {"0", "false", "off", "no"}
        self._model: Any | None = None
        self._voice: Any | None = None
        self._lock = threading.RLock()
        # Auto-select CUDA when a GPU-enabled PyTorch build is installed.
        # Override with OPENJARVIS_ARMENIAN_TTS_DEVICE=cpu to save VRAM.
        self._device_preference = os.environ.get(
            "OPENJARVIS_ARMENIAN_TTS_DEVICE", "auto"
        ).strip().lower()
        self._device = "cpu"

    def health(self) -> bool:
        """Check dependencies and configuration without loading the model."""
        return self._config_path.is_file() and (
            importlib.util.find_spec("pocket_tts") is not None
        )

    def _model_config_for_variant(self) -> Path:
        """Preserve the working YAML; use a cached derived config for run5."""
        if self._variant == "run4_60k":
            return self._config_path
        if self._variant != "run5_175k":
            raise ValueError(
                "OPENJARVIS_ARMENIAN_TTS_VARIANT must be run4_60k or run5_175k"
            )
        import yaml
        from huggingface_hub import hf_hub_download

        revision = "b9ea677231407e274bd9d8b0a1404a49b6247ae3"
        weights = hf_hub_download(
            repo_id="mnjoyan/pocket-tts-armenian",
            filename="run5_175k/model.safetensors",
            revision=revision,
        )
        tokenizer = hf_hub_download(
            repo_id="mnjoyan/pocket-tts-armenian",
            filename="run5_175k/tokenizer_hy5.model",
            revision=revision,
        )
        with self._config_path.open("r", encoding="utf-8") as source:
            config = copy.deepcopy(yaml.safe_load(source))
        config["weights_path"] = str(weights)
        config["flow_lm"]["lookup_table"]["tokenizer"] = "sentencepiece"
        config["flow_lm"]["lookup_table"]["tokenizer_path"] = str(tokenizer)
        config.pop("weights_path_without_voice_cloning", None)

        dest = Path.home() / ".openjarvis" / "tts-configs" / "run5_175k.yaml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        # The original, known-working run4 config is never overwritten.
        dest.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return dest

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if not self._config_path.is_file():
            raise RuntimeError(
                "Armenian Pocket-TTS config not found: "
                f"{self._config_path}"
            )
        try:
            from pocket_tts import TTSModel
        except ImportError as exc:
            raise RuntimeError(
                "Armenian voice requires pocket-tts in OpenJarvis's environment"
            ) from exc

        requested = self._device_preference
        if requested not in {"auto", "cuda", "cpu"}:
            raise ValueError(
                "OPENJARVIS_ARMENIAN_TTS_DEVICE must be auto, cuda, or cpu"
            )
        try:
            import torch
        except ImportError:
            cuda_available = False
        else:
            cuda_available = bool(torch.cuda.is_available())

        if requested == "cuda" and not cuda_available:
            raise RuntimeError(
                "CUDA requested for Armenian TTS, but PyTorch CUDA is unavailable"
            )

        device = "cuda" if (requested != "cpu" and cuda_available) else "cpu"
        model = TTSModel.load_model(config=str(self._model_config_for_variant()))
        if device == "cuda":
            try:
                # Move before creating the voice state, as in the successful benchmark.
                model = model.to("cuda")
            except (RuntimeError, OSError) as exc:
                if requested == "cuda":
                    raise
                import logging

                logging.getLogger(__name__).warning(
                    "Armenian Pocket-TTS GPU unavailable (%s); falling back to CPU", exc
                )
                model = model.to("cpu")
                device = "cpu"

        voice = model.get_state_for_audio_prompt(self._voice_prompt)
        self._model, self._voice = model, voice
        self._device = device

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = _VOICE_ID,
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        if not text.strip():
            raise ValueError("Text cannot be empty")
        if voice_id not in ("", _VOICE_ID):
            raise ValueError(
                f"Unsupported Armenian Pocket-TTS voice ID: {voice_id!r}"
            )
        if speed != 1.0:
            raise ValueError("Armenian Pocket-TTS currently supports speed=1.0 only")
        if output_format.lower() != "wav":
            raise ValueError("Armenian Pocket-TTS currently supports WAV only")

        import soundfile as sf

        with self._lock:
            self._ensure_loaded()
            # Only speech input is normalized; displayed chat messages stay original.
            # The fine-tune was trained on hy_text.normalise() output.
            # Apply author rules after the local pronunciation lexicon.
            speakable_text = normalize_for_pocket_training(
                normalize_armenian_speech(text)
            )
            audio = self._model.generate_audio(self._voice, speakable_text)
            samples = audio.detach().cpu().numpy()
            sample_rate = int(self._model.sample_rate)
            if self._trim_pauses:
                samples = shorten_long_pauses(samples, sample_rate)

            output = io.BytesIO()
            sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
            duration = len(samples) / sample_rate

        return TTSResult(
            audio=output.getvalue(),
            format="wav",
            duration_seconds=duration,
            voice_id=_VOICE_ID,
            sample_rate=sample_rate,
            metadata={"backend": self.backend_id, "language": "hy", "device": self._device, "variant": self._variant},
        )

    def available_voices(self) -> List[str]:
        return [_VOICE_ID]
