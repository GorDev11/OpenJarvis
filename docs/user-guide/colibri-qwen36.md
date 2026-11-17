# Colibri + Qwen3.6-35B-A3B (optional local inference)

OpenJarvis Armenian Desktop supports the **Colibri** OpenAI-compatible model
server as a separate, explicit inference choice. Ollama stays installed and can
be reselected at any time.

## Installation in the Desktop

1. Open **Settings → Inference source** and choose
   **Colibri · Qwen3.6-35B-A3B (local)**.
2. Read the confirmation and select **Install / Resume (~23 GB)**. This starts
   the official Colibri setup for the chosen model, using an upstream Git commit
   pinned in `scripts/setup_colibri_qwen36.py`. No download begins on app launch.
3. Watch **Installation log** and the readiness indicator. The model is fetched
   from the upstream-approved checkpoint and may take significant time.
   Interrupted downloads can be resumed by clicking Install / Resume again.
4. When the indicator shows **Ready** and a discovered model ID, optionally
   click **Test tool calling**. This probes the model's OpenAI-compatible
   function-calling output. An unsuccessful test is reported, not silently
   treated as success.
5. Click **Save inference source**, then restart OpenJarvis. On subsequent
   launches, the Desktop attempts to start an **already installed** Colibri
   server, but never initiates a first-time model download without consent.

The default loopback endpoint is **http://127.0.0.1:19000/v1**. Its
`GET /v1/models` must return a Qwen3.6 35B model before the Desktop offers to
save it. OpenJarvis's API stays isolated on its own port (18761 for Preview).
The Colibri model ID is **discovered from the running server**, not guessed.

## Resource and security notes

- The pinned Colibri setup catalog names
  `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64` and estimates a **23.1 GB**
  download and **20 GB recommended RAM**. Free disk space beyond this estimate
  is needed for installation and temporary files.
- Windows GPU acceleration can require additional **MSYS2 UCRT64 and
  CUDA/Vulkan** components. The official Colibri setup selects a compatible
  backend or reports exactly what is missing. Prebuilt builds may use CPU;
  hardware performance must be measured on the user's computer.
- Installation sources are downloaded only from the pinned
  `JustVugg/colibri` GitHub revision. Existing folders with other remotes or
  uncommitted edits are **never reset, cleaned, or overwritten**.
- Colibri serves only on **127.0.0.1**, not the public network. The chosen
  port is 19000. If another service occupies it, installation refuses to
  silently switch ports.
- Tools still belong to OpenJarvis agents, not the model server. Colibri
  supplies inference and OpenAI `tool_calls`, but it does **not** itself read
  YouTube transcripts, Gmail, or arbitrary websites. These require configured,
  permitted OpenJarvis tools. Tool-calling reliability depends on the loaded
  model and is not guaranteed by API support alone.
- The tool-call diagnostic only asks the model for a **calculator** call; it
  never executes a system-changing command.
- Switching back to **Bundled Ollama** does not delete downloaded Colibri
  model files. Nothing installs, changes, or removes Ollama automatically.

## Troubleshooting

If the server is unavailable, check the inline **Installation log**. Colibri
writes the model and server configuration in its own setup location.
The Desktop invokes `c/coli start --background --no-browser` only after the
user's first installation. If the checkpoint is still loading, readiness may
take several minutes. Make sure the `model` shown in Settings matches the
actual model ID reported by `/v1/models`.

Colibri documentation:
- https://github.com/JustVugg/colibri
- https://github.com/JustVugg/colibri/blob/main/docs/AI_SETUP.md
- https://github.com/JustVugg/colibri/blob/main/docs/api.md
