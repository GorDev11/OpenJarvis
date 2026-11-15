"""Optional local Eastern Armenian Pocket-TTS backend.

Set OPENJARVIS_ARMENIAN_TTS_CONFIG to a previously tested Pocket-TTS YAML,
or keep the default file at ~/OpenJarvis-Armenian-TTS/config_armenian.yaml.
The model loads lazily on first speech synthesis, and is then reused.
"""

from __future__ import annotations

import importlib.util
import io
import os
import threading
from pathlib import Path
from typing import Any, List

from openjarvis.core.registry import TTSRegistry
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
        self._model: Any | None = None
        self._voice: Any | None = None
        self._lock = threading.RLock()

    def health(self) -> bool:
        """Check dependencies and configuration without loading the model."""
        return self._config_path.is_file() and (
            importlib.util.find_spec("pocket_tts") is not None
        )

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

        model = TTSModel.load_model(config=str(self._config_path))
        voice = model.get_state_for_audio_prompt(self._voice_prompt)
        self._model, self._voice = model, voice

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
            audio = self._model.generate_audio(self._voice, text)
            samples = audio.detach().cpu().numpy()
            sample_rate = int(self._model.sample_rate)

            output = io.BytesIO()
            sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
            duration = len(samples) / sample_rate

        return TTSResult(
            audio=output.getvalue(),
            format="wav",
            duration_seconds=duration,
            voice_id=_VOICE_ID,
            sample_rate=sample_rate,
            metadata={"backend": self.backend_id, "language": "hy"},
        )

    def available_voices(self) -> List[str]:
        return [_VOICE_ID]
