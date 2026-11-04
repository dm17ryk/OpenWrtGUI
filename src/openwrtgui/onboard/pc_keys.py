"""SSH keys this PC already has. A router that trusts one of them needs no new key."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

import asyncssh

log = logging.getLogger(__name__)

KEY_NAMES = ("id_ed25519", "id_ecdsa", "id_rsa")


def ssh_dirs() -> list[Path]:
    """%HOME%\\.ssh first (the bench PCs set HOME to C:\\Essence_SC\\home), then the profile's."""
    dirs: list[Path] = []
    home = os.environ.get("HOME")
    if home:
        dirs.append(Path(home) / ".ssh")
    profile = Path.home() / ".ssh"
    if profile not in dirs:
        dirs.append(profile)
    return dirs


def find_pc_keys(dirs: Iterable[Path]) -> list[Path]:
    """Private keys that load without a passphrase, each file once, in KEY_NAMES order per folder."""
    found: list[Path] = []
    seen: set[Path] = set()
    for folder in dirs:
        for name in KEY_NAMES:
            path = folder / name
            if not path.is_file() or path.resolve() in seen:
                continue
            seen.add(path.resolve())
            try:
                asyncssh.read_private_key(str(path))
            except (OSError, ValueError) as exc:  # KeyImportError is a ValueError: passphrase or not a key
                log.info("skipping %s: %s", path, exc)
                continue
            found.append(path)
    return found
