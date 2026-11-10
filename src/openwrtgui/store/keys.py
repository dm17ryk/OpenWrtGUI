"""The app's own SSH key: one ed25519 key per PC, kept in the data folder."""

from __future__ import annotations

import getpass
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncssh

PRIVATE_NAME = "id_ed25519"


@dataclass(frozen=True)
class AppKey:
    private_path: Path
    public_line: str
    fingerprint: str


def user_only_mode(path: Path) -> int:
    """The POSIX mode for the current user only: a folder keeps its search bit, or nothing goes inside."""
    return 0o700 if path.is_dir() else 0o600


def restrict_to_user(path: Path) -> None:
    """Make a file (the private key, a backup) or a folder (the backups) usable by the current user only."""
    if sys.platform == "win32":
        user = os.environ.get("USERNAME") or getpass.getuser()
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            check=True,
            capture_output=True,
        )
    else:
        path.chmod(user_only_mode(path))


def load_or_create_app_key(keys_dir: Path, comment: str | None = None) -> AppKey:
    private_path = keys_dir / PRIVATE_NAME
    public_path = keys_dir / (PRIVATE_NAME + ".pub")
    if private_path.exists():
        key = asyncssh.read_private_key(str(private_path))
    else:
        keys_dir.mkdir(parents=True, exist_ok=True)
        key = asyncssh.generate_private_key(
            "ssh-ed25519", comment=comment or f"openwrtgui@{socket.gethostname()}"
        )
        key.write_private_key(str(private_path))
        restrict_to_user(private_path)
        key.write_public_key(str(public_path))
    public_line = key.export_public_key("openssh").decode("ascii").strip()
    if not public_path.exists():
        public_path.write_text(public_line + "\n", encoding="utf-8")
    return AppKey(
        private_path=private_path,
        public_line=public_line,
        fingerprint=key.get_fingerprint("sha256"),
    )
