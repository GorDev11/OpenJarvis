# OpenJarvis updates from `main`

The canonical source of truth is now **GorDev11/OpenJarvis, branch `main`**.
The earlier `feature/armenian-voice` checkout is supported **only for a
one-time, fast-forward migration**; new work belongs on `main`.

## In the Windows desktop app

New preview builds of OpenJarvis Armenian Preview have a separate **GitHub
main updates** indicator at the top of the chat and a manual **Check GitHub
main** action in Settings → Updates.

- On opening the app, and every 15 seconds while open (and on app focus or reconnect), the desktop checks
  `refs/heads/main` on `https://github.com/GorDev11/OpenJarvis.git`.
- When a different commit is published, the UI offers **Թարմացնել / Update**.
- Clicking updates only the **installed Python backend Git source** in the
  install-scoped `src` checkout. The Desktop stops **only its owned**
  server processes, fetches `main`, refuses to overwrite local modifications
  or diverged history, fast-forwards, and starts the managed backend again.
  Startup runs the normal dependency sync and readiness checks.
- The first update can migrate the previous Preview's
  `feature/armenian-voice` checkout to `main`.
- Offline, Git, merge, or dependency errors are surfaced; the tool does not
  reset, force-push, delete untracked files or run `git reset --hard`.

**Desktop binary limitation:** Git source updates **cannot** replace the
already installed Tauri `.exe`, its compiled React UI, or its tray menus.
A new installer is required for changes to those parts. This application
must not execute arbitrary unsigned code from GitHub on a timer. For
fully automatic desktop binary replacement, provision a **separately
signed Tauri update channel** for the owner's releases and verify its
public key and signatures. Never point the Preview to the upstream
`open-jarvis/OpenJarvis` updater or disable signature verification.

The existing stable updater remains intentionally disabled in Armenian
Preview until that *owner-controlled, signed* channel is configured.
The source-update button works independently of desktop binary updates.

## Initial installation of this UI

The currently installed Preview `.exe` predates this feature. Building or
installing **one new Preview installer from `main`** is required to get
the new UI and native update commands. The GitHub workflow
`OpenJarvis Main Windows Preview` builds an unsigned test installer as an
Actions artifact. The user must install it explicitly. Subsequent
**backend Python** changes will be available by one click.

The old local development checkout `C:\Users\harut\OpenJarvis`
is separate from the installed Preview's
`%LOCALAPPDATA%\OpenJarvis Armenian Preview\src` checkout.
Clicking Update updates **the latter** only.

For local contributors, one-time manual migration of the development clone
can use `git fetch origin main` then `git switch main` and
`git pull --ff-only origin main` after verifying the worktree is clean.

## Deployment checklist

1. Update and rebuild Preview from `main` with the
   `armenian-preview` feature; run Rust, frontend and Python tests.
2. Install the new Preview; check GitHub main in Settings.
3. Push a harmless test commit to `main`. Confirm an update banner appears
   on the installed Preview within about 15 seconds while online (network conditions permitting).
4. Click Update and confirm the installed `src` checkout is now on
   `main` at the new SHA, and the owned backend restarts.
5. Validate dirty worktree refusal, offline failure, same-SHA no-op, and
   no updates to unrelated checkouts.
6. Separately provision signing before claiming that Desktop `.exe`
   updates are automatic. Never reuse the upstream release signing identity.


## Preview API port isolation

The official OpenJarvis Desktop remains on loopback port **8000**. The
`armenian-preview` Tauri build runs its own managed Python API on
`127.0.0.1:18761` to avoid the Windows 10048 collision when both editions
are installed. The UI obtains that URL through the native `get_api_base`
command. The shared Ollama model server continues to use `127.0.0.1:11434`.
No third-party server is terminated. A foreign listener on the Preview's
dedicated port is rejected rather than silently adopted. An explicitly
configured custom API URL in Settings still takes precedence.
A new Preview installer is needed for this native Rust change.

## Desktop update detection smoke test

A documentation-only commit was created on 2026-11-17 to exercise the
Armenian Preview's GitHub `main` update banner and its 15-second check.
No application code, model configuration, API keys, or Windows settings
were changed. Once this commit is detected, selecting **Թարմացնել / Update**
should fast-forward the installation-scoped source checkout and restart
the managed Python backend if its working tree is clean.

## Automatic update notification smoke test — second pass

This documentation-only change exercises the Armenian Preview notification
without altering the Python backend, Rust launcher, frontend, settings, or models.

Expected: a running Preview built before this commit detects the new GitHub
`main` SHA automatically, shows an update banner and **Թարմացնել / Update**
button, and waits for the user to choose whether to apply it. The source
update should remain fast-forward-only, with no destructive reset.
