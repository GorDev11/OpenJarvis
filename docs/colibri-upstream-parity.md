# Colibri upstream compatibility contract

This project integrates the official **JustVugg/colibri** runtime rather than a replacement inference engine.

Official upstream: https://github.com/JustVugg/colibri

## User requirement

OpenJarvis must preserve the officially documented Colibri behavior. Merely displaying
"Colibri" in the UI is not sufficient evidence of full feature or performance parity.

The current installer pins upstream commit `0a5504a1dc64f86fcd0fe7db298b0448c730e7e6`
for reproducible installs. It invokes Colibri's own `c/coli setup`, selecting
`qwen36-35b`, localhost port `19000`, background server and no browser.
It does **not** implement Colibri inference algorithms itself. The pin must be
reviewed and updated deliberately when comparing with newer upstream documentation.

## Required verification before claiming parity

1. **Runtime and model:** verify the upstream engine and real model ID through
   official Colibri `status --json` and `/v1/models`, not just an open HTTP port.
2. **Hardware backend:** use Colibri's own backend selection and runtime. Distinguish
   the *configured* backend (from official `setup.json`) from actual GPU work
   (verify the server log and active generation). Never claim CUDA merely because
   `nvidia-smi` shows allocated VRAM.
3. **Model integrity:** do not silently change quantization, routed expert semantics,
   model weights, or generation behavior compared with the selected upstream
   Colibri checkpoint.
4. **API capabilities:** verify streaming, reasoning, tool calls, and any enabled
   advanced features against direct upstream API calls with the *same* request.
5. **Model catalog:** adding other supported Colibri models must not break the
   default Qwen3.6 integration. Current OpenJarvis setup is Qwen-specific; full
   catalog parity is **not yet implemented**.
6. **Speed:** measure prompt prefill, first-token latency, token generation rate,
   and tool orchestration time separately. Compare direct Colibri to OpenJarvis
   on the same hardware and settings; upstream benchmarks on other GPUs are
   not guaranteed.
7. **Security and updates:** preserve user opt-in for downloads and software
   installs. Pinned upstream source must be reviewed before upgrading. Release
   verified, signed OpenJarvis desktop updates from `main`.
8. **Regression:** Windows x64 signed build, frontend tests and live GPU/backend
   checks must pass before reporting completion.

## Where to check official state (Windows)

Colibri's upstream default setup file is:
`%LOCALAPPDATA%\colibri\setup.json`

Its server log is:
`%LOCALAPPDATA%\colibri\logs\serve.log`

For a privacy-preserving check, inspect only `backend`, `engine`, model and
server status. Do not paste the entire `setup.json` because it can contain
environment variables. Only share redacted excerpts of the log if needed.

PowerShell (read-only):
```powershell
$path = Join-Path $env:LOCALAPPDATA 'colibri\setup.json'
if (Test-Path $path) {
    $config = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    [pscustomobject]@{
        Backend = $config.backend
        Engine  = $config.engine
        Model   = $config.model.name
        Port    = $config.port
    }
} else {
    Write-Host 'Official Colibri setup.json was not found.'
}
```

The default OpenJarvis `Settings > Colibri` panel now reports the configured
backend from this upstream file. This is diagnostic transparency; it does not
itself improve inference throughput or prove that the selected backend is
actually executing GPU kernels.

## Open work

- Expose official Colibri diagnostics (`status --json`, `doctor --json`,
  speed and server logs) in a safe UI.
- Support compatible Colibri model selection beyond the initial Qwen3.6 model.
- Provide user-controlled backend configuration/reconfiguration through the
  official launcher without destructive reinstall or unintended fallback.
- Add end-to-end direct-engine vs OpenJarvis parity benchmarks.

Until those items are completed and tested, **do not call the integration
fully equivalent to every official Colibri feature**.
