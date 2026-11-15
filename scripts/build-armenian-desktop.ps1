# Build a separate Windows 11 Desktop test installer for Armenian voice.
# PowerShell: powershell -ExecutionPolicy Bypass -File .\scripts\build-armenian-desktop.ps1
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontend = Join-Path $project "frontend"
$previewConfig = Join-Path $frontend "src-tauri\tauri.armenian-preview.conf.json"

function Assert-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $name. Install it and try again."
    }
}

function Run-Checked($exe, [string[]]$arguments) {
    Write-Host ("> " + $exe + " " + ($arguments -join " ")) -ForegroundColor Cyan
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE : $exe"
    }
}

Set-Location $project
Write-Host "Building isolated Armenian Desktop preview from: $project" -ForegroundColor Green
Assert-Command "uv"
Assert-Command "npm.cmd"
Assert-Command "npx.cmd"
Assert-Command "cargo"
Assert-Command "rustc"
if (-not (Test-Path $previewConfig)) {
    throw "Preview Tauri config missing. Pull feature/armenian-voice first."
}
$branch = (& git branch --show-current 2>$null).Trim()
if ($branch -ne "feature/armenian-voice") {
    throw "Expected feature/armenian-voice branch, found '$branch'."
}
Write-Host ("Node: " + ((& node --version) -join ""))
Write-Host ("npm: " + ((& npm.cmd --version) -join ""))
Write-Host ("Rust: " + ((& rustc --version) -join ""))

# Desktop invokes uv sync on launch. Validate the same extras now.
Run-Checked "uv" @(
    "sync", "--extra", "dev", "--extra", "desktop",
    "--extra", "inference-cloud", "--extra", "inference-google",
    "--group", "desktop-native"
)

if (-not $SkipTests) {
    Run-Checked "uv" @(
        "run", "--no-sync", "python", "-m", "pytest",
        "tests/speech/test_armenian_audio.py",
        "tests/speech/test_armenian_training_text.py",
        "tests/speech/test_armenian_pronunciation.py",
        "tests/speech/test_armenian_pocket_tts.py",
        "-q"
    )
}

$gpu = & (Join-Path $project ".venv\Scripts\python.exe") -c "import torch; print(torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "PyTorch CUDA check failed" }
Write-Host "PyTorch CUDA available: $gpu"

Push-Location $frontend
try {
    Run-Checked "npm.cmd" @("ci")
    if (-not $SkipTests) { Run-Checked "npm.cmd" @("test") }
    Run-Checked "npm.cmd" @("run", "build")
    # Tauri calls npm run build:tauri; NSIS creates an isolated installer.
    Run-Checked "npx.cmd" @(
        "tauri", "build", "--bundles", "nsis",
        "--config", "src-tauri/tauri.armenian-preview.conf.json"
    )
} finally {
    Pop-Location
}

$dir = Join-Path $frontend "src-tauri\target\release\bundle\nsis"
$installers = @(Get-ChildItem -Path $dir -Filter "*.exe" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*Armenian*" -or $_.Name -like "*Preview*" })
if ($installers.Count -eq 0) {
    Write-Warning "Build succeeded but preview installer wasn't found in $dir; check the Tauri output."
} else {
    Write-Host "Desktop preview installer:" -ForegroundColor Green
    $installers | Select-Object FullName, Length | Format-Table -AutoSize
}
Write-Host "Stable Desktop and Git main branch were not modified." -ForegroundColor Green
