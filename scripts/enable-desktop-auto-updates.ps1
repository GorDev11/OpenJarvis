# One-time enrollment of the owner-signed Windows Desktop update channel.
# Usage from the GitHub main checkout:
#   powershell -ExecutionPolicy Bypass -File .\scripts\enable-desktop-auto-updates.ps1
#
# Never prints or commits the private signing key or password.
# After the first signed .exe is installed, subsequent updates are delivered
# by the built-in OpenJarvis updater. No more PowerShell is required.
param(
    [switch]$NoDispatch
)

$ErrorActionPreference = "Stop"
$repo = "GorDev11/OpenJarvis"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontend = Join-Path $root "frontend"
if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is required on Windows." }

function Assert-Exe([string]$command) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command not found. Install it before continuing."
    }
}

function Assert-Exit([string]$name) {
    if ($LASTEXITCODE -ne 0) {
        throw "$name failed with exit code $LASTEXITCODE."
    }
}

Assert-Exe "git"
Assert-Exe "npm.cmd"
Assert-Exe "gh"
$branch = (& git -C $root branch --show-current).Trim()
Assert-Exit "git branch"
if ($branch -ne "main") {
    throw "Only the main branch is supported. Current branch: $branch"
}
$origin = (& git -C $root remote get-url origin).Trim()
Assert-Exit "git remote"
if ($origin -notmatch '^(https://github\.com/|git@github\.com:)GorDev11/OpenJarvis(\.git)?$') {
    throw "The Git origin is not the owner's GorDev11/OpenJarvis repository."
}

# Authenticate the owner via the normal GitHub CLI flow. Never collect GitHub
# access tokens in the script or store them in the OpenJarvis repository.
& gh auth status --hostname github.com 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Sign in to GitHub in the browser (one time)." -ForegroundColor Cyan
    & gh auth login --hostname github.com --git-protocol https --web
    Assert-Exit "GitHub sign-in"
}
& gh repo view $repo --json nameWithOwner --jq ".nameWithOwner" | Out-Null
Assert-Exit "GitHub repository access"

$signingDir = Join-Path $env:LOCALAPPDATA "OpenJarvis\Signing"
New-Item -ItemType Directory -Force -Path $signingDir | Out-Null
$keyPath = Join-Path $signingDir "desktop-main.key"
$pubPath = "$keyPath.pub"

if ((Test-Path $keyPath) -xor (Test-Path $pubPath)) {
    throw "Only one half of the signing keypair exists in $signingDir. Restore the matching pair; do NOT overwrite the key."
}

if (-not (Test-Path $keyPath)) {
    $tauri = Join-Path $frontend "node_modules\.bin\tauri.cmd"
    if (-not (Test-Path $tauri)) {
        Write-Host "Installing the checked-in frontend dependencies..." -ForegroundColor Cyan
        Push-Location $frontend
        try {
            & npm.cmd ci --no-audit --no-fund
            Assert-Exit "npm ci"
        } finally { Pop-Location }
    }
    Write-Host "Creating the updater keypair in your Windows profile..." -ForegroundColor Cyan
    Write-Host "Set a strong password when Tauri asks for one; keep an offline backup."
    # Interactive Tauri CLI prompts securely; never pass the private password
    # via a process command-line argument or commit it into the repository.
    & $tauri signer generate --write-keys $keyPath
    Assert-Exit "Tauri signer generate"
}

if (-not (Test-Path $keyPath) -or -not (Test-Path $pubPath)) {
    throw "Tauri signing keypair was not generated."
}

# gh secret set reads from standard input; never pass the key as an argument.
# A masked/owner-controlled repository secret will be used only in Actions.
Get-Content -LiteralPath $keyPath -Raw | & gh secret set TAURI_SIGNING_PRIVATE_KEY --repo $repo
Assert-Exit "GitHub private signing key secret"

Write-Host "Re-enter your Tauri signing password for GitHub Actions." -ForegroundColor Cyan
Write-Host "If you generated an unencrypted key, press Enter."
$secure = Read-Host "Private-key password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ($password.Length -gt 0) {
        $password | & gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD --repo $repo
        Assert-Exit "GitHub signing password secret"
    } else {
        # An old password is harmful when the key is unencrypted.
        $known = & gh secret list --repo $repo --json name --jq '.[].name'
        Assert-Exit "GitHub secret list"
        if ($known -contains "TAURI_SIGNING_PRIVATE_KEY_PASSWORD") {
            & gh secret delete TAURI_SIGNING_PRIVATE_KEY_PASSWORD --repo $repo
            Assert-Exit "Remove obsolete signing password secret"
        }
    }
} finally {
    if ($null -ne $password) { $password = $null }
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$publicKey = (Get-Content -LiteralPath $pubPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($publicKey)) { throw "Public key is empty." }
& gh variable set TAURI_SIGNING_PUBLIC_KEY --repo $repo --body $publicKey
Assert-Exit "GitHub public signing key variable"

Write-Host "Signing keys registered for $repo." -ForegroundColor Green
Write-Host "Private key stays at $keyPath; back it up securely."
if (-not $NoDispatch) {
    & gh workflow run main-desktop-signed.yml --repo $repo --ref main
    Assert-Exit "Start signed Windows release"
    Write-Host "Signed release workflow started. Open:"
    Write-Host "https://github.com/$repo/actions/workflows/main-desktop-signed.yml"
}
Write-Host "Install the first owner-signed desktop-main release once." -ForegroundColor Yellow
Write-Host "After that, OpenJarvis updates its signed .exe internally without manual downloads."
