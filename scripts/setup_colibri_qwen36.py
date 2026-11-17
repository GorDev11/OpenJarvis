"""Explicit, resumable Colibri Qwen3.6 setup for OpenJarvis Desktop.

Only starts after the user clicks Install in Settings. The repository commit
is pinned, the remote is checked, and no existing checkout is reset or cleaned.
Uses the official Colibri installer and its built-in checksum verification.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import json


UPSTREAM = "https://github.com/JustVugg/colibri.git"
PINNED_COMMIT = "0a5504a1dc64f86fcd0fe7db298b0448c730e7e6"
MODEL = "qwen36-35b"
PORT = 19000


def installation_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".local" / "share") / "OpenJarvis" / "Colibri"


def accepted_origin(url: str) -> bool:
    return url.strip().lower().rstrip("/") in {
        "https://github.com/justvugg/colibri.git",
        "https://github.com/justvugg/colibri",
    }


def call(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def model_is_running() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/v1/models", timeout=3
        ) as response:
            data = json.load(response)
        names = [
            item.get("id", "").lower()
            for item in data.get("data", [])
            if isinstance(item, dict)
        ]
        return any(
            ("qwen" in name and ("35b" in name or "35-b" in name))
            for name in names
        )
    except (OSError, ValueError, TypeError, KeyError):
        return False


def ensure_source(target: Path) -> None:
    if target.exists():
        if not (target / ".git").exists():
            raise RuntimeError(
                f"{target} already exists but is not a Git checkout; not overwriting."
            )
        origin = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=target, text=True
        )
        if not accepted_origin(origin):
            raise RuntimeError("Existing Colibri folder has an untrusted Git remote.")
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=target, text=True
        )
        if dirty.strip():
            raise RuntimeError("Colibri checkout has local edits; refusing to overwrite.")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        call("git", "clone", "--no-checkout", "--depth", "1", UPSTREAM, str(target))
    call("git", "fetch", "--no-tags", "--depth", "1", "origin", PINNED_COMMIT, cwd=target)
    call("git", "checkout", "--detach", PINNED_COMMIT, cwd=target)


def main() -> int:
    install = installation_root()
    repo = install / "source"
    print("OpenJarvis Colibri setup · Qwen3.6-35B-A3B · approx. 23 GB", flush=True)
    print(f"Colibri source: {repo}", flush=True)
    if model_is_running():
        print("The selected Qwen3.6 model is already running on 127.0.0.1:19000.")
        return 0
    # Protect the fixed localhost port: the desktop will never connect to a
    # different service that Colibri silently started on an alternate port.
    with socket.socket() as test:
        try:
            test.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise RuntimeError(
                "Port 19000 is already occupied by a different service. "
                "Stop that service; no other ports will be tried."
            ) from exc
    if not shutil.which("git"):
        raise RuntimeError("Git is required. Install Git for Windows before retrying.")
    print("Checking pinned Colibri source...", flush=True)
    ensure_source(repo)
    launcher = repo / "c" / "coli"
    if not launcher.is_file():
        raise RuntimeError("Pinned Colibri launcher is missing.")
    print("Installing model with Colibri (download is resumable)...", flush=True)
    call(
        sys.executable, str(launcher), "setup", "--yes", "--model", MODEL,
        "--host", "127.0.0.1", "--port", str(PORT),
        "--background", "--no-browser",
        cwd=repo,
    )
    print("Colibri setup finished. The model may still be loading.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
