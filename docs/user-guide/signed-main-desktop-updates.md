# Owner-signed OpenJarvis Desktop releases from main

OpenJarvis now has two distinct update mechanisms, both with `main` as
the canonical source of truth:

1. **Backend Python source**: The UI checks every 15 seconds and can update
   the installed `src` Git checkout by one button press, followed by a
   managed backend restart. No signing keys are required for this path.
2. **Compiled Windows Desktop UI**: The existing Tauri updater can replace
   the executable, but **only with a properly signed release**. It must not
   accept unsigned GitHub Actions artifacts, and it must not use the
   upstream `open-jarvis/OpenJarvis` release feed.

## One-time signing setup (GitHub repository owner)

You must provision signing material under your control. NEVER commit or share
the private key, including through ChatGPT or an issue/PR.

**Simpler Windows setup:** From a trusted checkout on the `main` branch,
run `powershell -ExecutionPolicy Bypass -File .\\scripts\\enable-desktop-auto-updates.ps1`.
The script checks the correct GitHub remote, uses GitHub CLI authentication,
creates a private updater key in your Windows profile only if one does not
already exist, uploads only to GitHub Actions encrypted secrets, configures
the owner-controlled public key and starts the signed-release workflow. The
password is never printed or passed as a process argument. You must have
`git`, `npm` and the official `gh` CLI installed; the script never
silently installs new system software. Back up the private key and password
safely. If you already have a signing keypair, the script reuses it rather
than overwriting the key.

**The first signed release still requires one manual installation.** The
existing isolated Preview has no pinned trusted public key and cannot
securely update its own executable. After that one-time migration, future
signed `.exe` releases are verified by Tauri and installed inside OpenJarvis
without GitHub browsing or PowerShell.

- Create a Tauri updater signing keypair on your **trusted computer** using
  the Tauri CLI (`npx tauri signer generate` from the `frontend` folder);
  store the generated private key outside the repository in secure storage.
- In `GorDev11/OpenJarvis` → Settings → Secrets and variables → Actions,
  add repository **secret** `TAURI_SIGNING_PRIVATE_KEY` containing the
  private key and, if used, secret
  `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.
- Add repository **variable** `TAURI_SIGNING_PUBLIC_KEY` containing exactly
  the matching public key text.
- Run the workflow `OpenJarvis Main Signed Desktop Updates` from `main`.
  Its build runs frontend and Rust tests, generates version
  `1.1.<workflow run number>`, signs the NSIS updater archive, and publishes
  `desktop-main` assets and `latest.json` to **your own** GitHub Releases.
  The manifest is published last, only after signed assets exist.

The signing workflow automatically skips when the public key variable is not
set. This avoids publishing unverified binaries. With a public key but no
matching private key, the build fails visibly and publishes nothing.

**First installation is manual:** The current unsigned Preview was compiled
with its updater disabled, so it cannot bootstrap a trusted public signing
key from the internet. Install the first owner-signed `desktop-main` installer
yourself from GitHub Releases. After that, the built-in Tauri Update Checker
automatically checks newer signed releases every minute, supports
one-click download/install, and can optionally install signed updates after
60 seconds of inactivity. The opt-in setting explicitly warns that Windows
will relaunch the app. Updates are never installed while an AI response is
streaming. The signed build uses
`frontend/.env.armenian-release` to enable the owner's updater endpoint.
The old unsigned Preview uses `.env.armenian-preview` and stays isolated.

**No unsigned silent execution.** Do not replace the release signing key
without a signed migration plan or manual reinstall. Protect the owner
repository against unreviewed commits because CI can sign code from `main`.

## One unified update button

The main Git update card is the sole user-facing update action. The unsigned
Preview can fast-forward the Python backend only. Once a signed Desktop
release has been provisioned, the same card checks the owner-controlled
signed channel and prefers a verified signed Desktop installer whenever
one is available. Clicking it downloads the signed release, safely
fast-forwards the owned Python source (refusing dirty checkouts), then
hands off to Tauri for installation. Windows exits during installation;
if Windows does not relaunch the app, start it normally from the Start menu.

A Git commit is detected before CI has finished producing the signed
installer. During that interval the existing source-only update remains
available. Once CI publishes a new signed release, the unified card
discovers it at the next signed check. No unsigned artifact is ever executed.

**One-time bootstrap is unavoidable:** install the first signed release
manually after configuring the signing keys. Thereafter subsequent signed
releases use the in-app Update action. Pushes changing frontend or Python
application code trigger the signed workflow; documentation-only commits
only trigger the source checker. Automatic installation remains opt-in and never bypasses signature
validation, streaming safety, or the first trusted bootstrap.

**Validation**: Confirm the Windows installer was built from `main`, the
installed `src` checkout is on `main`, the release manifest has
`windows-x86_64`, and the signature is accepted by Tauri. Do not claim
automatic executable updates work until those tests pass.
