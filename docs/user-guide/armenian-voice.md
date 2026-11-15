# Local Armenian voice (Pocket-TTS)

This optional backend connects a local Eastern Armenian Pocket-TTS model to
OpenJarvis's existing speech API and chat read-aloud controls.

It uses the model/configuration already tested separately in
~/OpenJarvis-Armenian-TTS, and does not require a cloud API key.

## Prerequisites

- A working OpenJarvis Desktop installation (Python environment in .venv)
- Pocket-TTS model assets and configuration:
  ~/OpenJarvis-Armenian-TTS/config_armenian.yaml
- This config must refer to accessible model weights and tokenizer files in
  the local Hugging Face cache.

## Install dependencies on Windows

The fork declares `pocket-tts==4.0.1` and the tested
`torch==2.13.0` CUDA 13.0 wheel for Windows Desktop in its Python dependency
configuration. This matters because Desktop runs `uv sync` on launch and
removes manually installed packages that aren't listed in its lockfile.
Other operating systems continue resolving PyTorch through PyPI.

The TTS backend now uses CUDA automatically when `torch.cuda.is_available()`
is true. To force CPU mode (e.g., if VRAM is needed by Ollama), set
`OPENJARVIS_ARMENIAN_TTS_DEVICE=cpu` in the Desktop process environment.
Alternatively, set `OPENJARVIS_ARMENIAN_TTS_DEVICE=cuda` to require CUDA
explicitly (and fail if CUDA is unavailable). The default is `auto`.

For the RTX 3060 test system, a short Armenian utterance took about
1.10–1.16 seconds with the CUDA wheel, compared with 7–9 seconds on CPU.
Long replies still require more processing. The experimental Chat frontend
can play short speech segments successively after a text reply finishes,
while the existing speech API returns complete WAV files for each request.
Token-by-token live speech remains a separate improvement.

After pulling the feature branch, close Desktop and run once from the
OpenJarvis checkout:

    uv lock
    uv sync --extra desktop --extra inference-cloud --extra inference-google --group desktop-native

Commit the regenerated `uv.lock` to the feature branch to keep installs
reproducible. After this, Desktop's own dependency synchronization should
retain Pocket-TTS, and the separate .venv-pocket test environment remains
independent.

Before restarting Desktop, verify CUDA in the main OpenJarvis environment:

    .\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"

On the validated RTX 3060 machine, expect a `+cu130` PyTorch version
and `True`. The first model load may still take longer than subsequent
synthesis calls.


## Select the backend

Edit ~/.openjarvis/config.toml. Under its existing [speech] section, set
these values (do not create a second [speech] section):

    tts_backend = "armenian_pocket"
    voice_id = "hy-default"
    voice_speed = 1.0

Optional: set language = "hy" in the same section to request Armenian
speech recognition. Speech recognition uses Faster-Whisper separately.

By default the backend loads:
~/OpenJarvis-Armenian-TTS/config_armenian.yaml

For a different path set OPENJARVIS_ARMENIAN_TTS_CONFIG in the process
environment before launching OpenJarvis.

The voice prompt defaults to:
hf://kyutai/tts-voices/alba-mackenna/casual.wav

To use a different audio prompt, set
OPENJARVIS_ARMENIAN_TTS_VOICE_PROMPT before launching OpenJarvis.

## Verify

Completely quit and restart the OpenJarvis Desktop app, then:

    Invoke-RestMethod "http://127.0.0.1:8000/v1/speech/tts/health" | Format-List

Expected result includes available = True and backend = armenian_pocket.

To synthesize speech through the *actual OpenJarvis API*:

    $body = @{text="Բարև, ես Ջարվիսն եմ։"} | ConvertTo-Json
    Invoke-WebRequest "http://127.0.0.1:8000/v1/speech/synthesize" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($body)) -OutFile "$env:TEMP\openjarvis-hy.wav"
    Start-Process "$env:TEMP\openjarvis-hy.wav"

Use the built-in read-aloud button in the Chat UI for normal use.

## Mixed Armenian and Latin text

The Armenian Pocket-TTS backend normalizes Latin technical names **only for
speech synthesis**. The chat answer remains unchanged visually. For example:

- `ChatGPT` -> `Չաթ Ջի Փի Թի`
- `Gemini` -> `Ջեմինի`
- `AI` -> `Էյ Այ`
- `OpenJarvis` -> `Օփեն Ջարվիս`
- `Wi-Fi` -> `Վայֆայ`; `MQTT` -> `Էմ Քյու Թի Թի`

There are also mappings for common AI tools, development technologies, and
abbreviations. Unknown Latin tokens inside Armenian paragraphs are spoken
letter by letter as a conservative fallback: arbitrary English names cannot
always be pronounced accurately from spelling alone. Full English passages,
URLs, and email addresses are not rewritten.

This applies to API speech generation as well as the Desktop/Chat voice.
After updating the Python source, **restart the Python backend** to load the
new normalizer; no new model weights are needed. Check the input transformation
without the model:

    cd "$env:USERPROFILE\OpenJarvis"
    .\.venv\Scripts\python.exe -c "from openjarvis.speech.armenian_pronunciation import normalize_armenian_speech as n; print(n('Ես օգտագործում եմ ChatGPT, Gemini, AI և OpenJarvis։'))"


## Author training-time normalization (pinned)

Pocket-TTS Armenian was trained with the author's
`configs/hy_text.py:normalise()` function. This is different from the custom
tech-name pronunciation dictionary: it transforms numerals into Armenian
words, normalizes Armenian punctuation and quotes, and handles remaining Latin
letters. The backend applies the tech-name dictionary first, then applies
the author's original normalizer immediately before synthesizing the audio.

At first use, `huggingface_hub` fetches **both** `configs/hy_itn.py` and
`configs/hy_text.py` from the exact model revision
`b9ea677231407e274bd9d8b0a1404a49b6247ae3`. The scripts are cached
locally (and imported as Python modules); neither the scripts nor weights are
copied into OpenJarvis Git. No newer revision is selected automatically.
Source and attribution: https://huggingface.co/mnjoyan/pocket-tts-armenian
(model repository license: CC-BY-4.0).

To prepare the dependency before the first audio request:

    cd "$env:USERPROFILE\OpenJarvis"
    .\.venv\Scripts\python.exe -c "from openjarvis.speech.armenian_pronunciation import normalize_armenian_speech as p; from openjarvis.speech.armenian_training_text import normalize_for_pocket_training as n; print(n(p('Ես օգտագործում եմ ChatGPT և 2026 թվականին։')))"

If the HF download fails, confirm Internet access or fetch
`configs/hy_itn.py` at the pinned revision with `hf_hub_download`.
To compare sound against the previous behavior, set
`OPENJARVIS_ARMENIAN_TTS_TRAINING_NORMALIZE=0` before starting the
Python server. Leave the voice/model and CUDA settings unchanged.

**Important:** the normalizer addresses text preparation, but it cannot
guarantee good pronunciation: the run4_60k model and the chosen voice
reference may still have accent or prosody limitations. Compare the same
short Armenian phrase before and after enabling the normalizer.

## Progressive read-aloud (experimental)

For the `armenian_pocket` backend, the Chat UI now divides long, completed
assistant replies into WAV-sized speech segments (approximately 120 characters
each). It begins playing the first segment while the next one is generated.
This uses the existing `/v1/speech/synthesize` API; other TTS backends keep
the previous whole-response playback behavior.

This feature affects the **frontend**, not only the Python API. Pulling the
feature branch updates the source but does **not** change an already installed
Tauri desktop executable, which contains a compiled frontend bundle.

Before rebuilding a Desktop app, run frontend checks:

    cd frontend
    npm ci
    npm test
    npm run build

A new Desktop build or a frontend development session is required to see the
progressive read-aloud behavior. Its deployment should be handled separately
from the validated Python CUDA acceleration. Cancellation and playback order
should be confirmed with the unit tests and then manually in the UI.

This is segment-by-segment progressive playback **after the text reply
finishes**, not token-level realtime streaming of the model response.

## Limitations

- Only one voice ID (hy-default) and WAV audio are supported.
- Voice speed must be exactly 1.0; other speeds raise an explicit error.
- Model loading on first use can be slow and depends on local memory.
- The default voice prompt can be fetched from Hugging Face on first use,
  unless already cached.
- Backend health checks dependencies and config existence, but does not run
  model inference. The first synthesis request is the functional test.
- The backend and model have not been tested on every GPU/Windows configuration.
- Keep large model weights and machine-specific cache paths out of Git.
- Do not overwrite the Windows tool-confirmation patch when merging upstream.

To disable, change tts_backend back to kokoro (or another configured backend)
and restart.
