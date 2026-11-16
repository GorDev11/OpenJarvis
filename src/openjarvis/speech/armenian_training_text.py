"""Apply the Armenian Pocket-TTS author's pinned training-time text rules.

The model card specifically requires configs/hy_text.py:normalise() before
synthesis. That module imports configs/hy_itn.py for digits_to_words() and
modern_ligature(). Keep both at the same immutable Hugging Face revision.

Upstream model and code: https://huggingface.co/mnjoyan/pocket-tts-armenian
License stated on the model repository: CC-BY-4.0.
The upstream source is downloaded into the HF cache, not committed here.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

_REPO = "mnjoyan/pocket-tts-armenian"
# Immutable revision matching the owner's known-working run4_60k weights.
_REVISION = "b9ea677231407e274bd9d8b0a1404a49b6247ae3"
_DISABLE_VALUE = {"0", "false", "off", "no"}


@lru_cache(maxsize=1)
def _load_training_normaliser() -> Callable[[str], str]:
    """Load the author's verified, revision-pinned normaliser once.

    Both files must exist in the same cached configs directory. The module
    inserts that directory into sys.path before importing hy_itn. We pin
    the revision so an upstream change cannot silently alter speech.
    """
    from huggingface_hub import hf_hub_download

    # Download the dependency first because hy_text.py imports it at load time.
    dependency = Path(
        hf_hub_download(
            repo_id=_REPO,
            filename="configs/hy_itn.py",
            revision=_REVISION,
        )
    )
    source = Path(
        hf_hub_download(
            repo_id=_REPO,
            filename="configs/hy_text.py",
            revision=_REVISION,
        )
    )
    if dependency.parent != source.parent:
        raise RuntimeError("Armenian TTS normaliser files are not in one directory")

    spec = importlib.util.spec_from_file_location("_openjarvis_hy_text_pinned", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Armenian TTS normaliser: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    normalise = getattr(module, "normalise", None)
    if not callable(normalise):
        raise RuntimeError(f"Armenian TTS normaliser has no normalise(): {source}")
    return normalise


def normalize_for_pocket_training(text: str) -> str:
    """Prepare the text exactly as the Armenian fine-tune expects.

    Set OPENJARVIS_ARMENIAN_TTS_TRAINING_NORMALIZE=0 for an emergency
    comparison or rollback without removing the working backend.
    """
    if (
        os.environ.get("OPENJARVIS_ARMENIAN_TTS_TRAINING_NORMALIZE", "1")
        .strip()
        .lower()
        in _DISABLE_VALUE
    ):
        return text
    if not text.strip():
        return text
    try:
        normalise = _load_training_normaliser()
    except Exception as exc:
        raise RuntimeError(
            "Cannot load the pinned Armenian TTS training normaliser. "
            "Download configs/hy_text.py and configs/hy_itn.py from "
            "mnjoyan/pocket-tts-armenian at revision " + _REVISION
        ) from exc
    return normalise(text)
