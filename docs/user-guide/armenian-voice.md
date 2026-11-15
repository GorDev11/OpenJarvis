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

The fork declares `pocket-tts==4.0.1` in the Desktop dependency extra
(on Windows). This is important: the Desktop executable runs `uv sync`
on launch and removes unlisted, manually installed Python packages.

After pulling the feature branch, close Desktop and run once from the
OpenJarvis checkout:

    uv lock
    uv sync --extra desktop --extra inference-cloud --extra inference-google --group desktop-native

Commit the regenerated `uv.lock` to the feature branch to keep installs
reproducible. After this, Desktop's own dependency synchronization should
retain Pocket-TTS, and the separate .venv-pocket test environment remains
independent.

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
