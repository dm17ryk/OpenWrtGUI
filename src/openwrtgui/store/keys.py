"""The app's own SSH key: one ed25519 key per PC, kept in the data folder, and its rotation (v1.1b)."""

from __future__ import annotations

import getpass
import json
import logging
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncssh

from openwrtgui.store import write_atomic

log = logging.getLogger(__name__)

PRIVATE_NAME = "id_ed25519"
NEXT_NAME = "id_ed25519.next"  # the next key while a rotation runs
ROTATION_NAME = "rotation.json"  # which routers have moved to it


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
        # S603/S607: Windows' own icacls on the app's key: fixed argv, no shell
        subprocess.run(  # noqa: S603
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],  # noqa: S607
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
    # the .pub follows the private key: a rotation cut off between the two leaves an old line here
    if not public_path.exists() or public_path.read_text(encoding="utf-8").strip() != public_line:
        write_atomic(public_path, public_line + "\n")
    return AppKey(
        private_path=private_path,
        public_line=public_line,
        fingerprint=key.get_fingerprint("sha256"),
    )


def _read_key(private_path: Path) -> AppKey:
    key = asyncssh.read_private_key(str(private_path))
    return AppKey(
        private_path=private_path,
        public_line=key.export_public_key("openssh").decode("ascii").strip(),
        fingerprint=key.get_fingerprint("sha256"),
    )


class AppKeyRing:
    """The app's key and, while a rotation runs (v1.1b, D8), the next one. Every connection offers both, the
    current one first (ruling R4); a router moves to the next key one at a time; `finish` makes the next key
    the current one once every router has moved. The rotation lives in the keys folder (R6): the next key
    (`id_ed25519.next` and its `.pub`) and `rotation.json`, the routers moved so far."""

    def __init__(self, keys_dir: Path, comment: str | None = None) -> None:
        self._dir = keys_dir
        self._comment = comment
        self._current = load_or_create_app_key(keys_dir, comment)
        self._next: AppKey | None = None
        self._moved: set[str] = set()
        self._load_rotation()

    @property
    def current(self) -> AppKey:
        """The key routers log in with: the old one while a rotation runs."""
        return self._current

    @property
    def next(self) -> AppKey | None:
        return self._next

    def login_paths(self) -> list[Path]:
        paths = [self._current.private_path]
        if self._next is not None:
            paths.append(self._next.private_path)
        return paths

    def fingerprints(self) -> frozenset[str]:
        found = {self._current.fingerprint}
        if self._next is not None:
            found.add(self._next.fingerprint)
        return frozenset(found)

    def moved(self) -> frozenset[str]:
        return frozenset(self._moved)

    def begin(self) -> AppKey:
        """Make the next key. Its private file is restricted to this user before its .pub or the rotation
        file is written; the rotation file comes last, so a begin cut short leaves no rotation."""
        if self._next is not None:
            raise ValueError("A key rotation is already under way")
        key = asyncssh.generate_private_key(
            "ssh-ed25519", comment=self._comment or f"openwrtgui@{socket.gethostname()}"
        )
        private_path = self._dir / NEXT_NAME
        key.write_private_key(str(private_path))
        restrict_to_user(private_path)
        key.write_public_key(str(self._dir / (NEXT_NAME + ".pub")))
        self._next = _read_key(private_path)
        self._moved = set()
        self._save_rotation()
        return self._next

    def mark_moved(self, router_id: str) -> None:
        if self._next is None:
            raise ValueError("No key rotation is under way")
        self._moved.add(router_id)
        self._save_rotation()

    def finish(self) -> AppKey:
        """The next key becomes the current one. Its private file replaces the old one first (the old private
        key is gone from then on), then the .pub, then the rotation's own files."""
        if self._next is None:
            raise ValueError("No key rotation is under way")
        private_path = self._dir / PRIVATE_NAME
        os.replace(self._dir / NEXT_NAME, private_path)
        new = AppKey(
            private_path=private_path, public_line=self._next.public_line, fingerprint=self._next.fingerprint
        )
        write_atomic(self._dir / (PRIVATE_NAME + ".pub"), new.public_line + "\n")
        self._drop_rotation_files()
        self._current, self._next, self._moved = new, None, set()
        return new

    def _save_rotation(self) -> None:
        assert self._next is not None  # noqa: S101 - callers check it
        state = {
            "old_fingerprint": self._current.fingerprint,
            "new_fingerprint": self._next.fingerprint,
            "moved": sorted(self._moved),
        }
        write_atomic(self._dir / ROTATION_NAME, json.dumps(state, indent=2) + "\n")

    def _drop_rotation_files(self) -> None:
        (self._dir / (NEXT_NAME + ".pub")).unlink(missing_ok=True)
        (self._dir / ROTATION_NAME).unlink(missing_ok=True)

    def _load_rotation(self) -> None:
        rotation = self._dir / ROTATION_NAME
        next_private = self._dir / NEXT_NAME
        if not rotation.exists():
            # a begin cut short before its rotation file: no router was given this key
            next_private.unlink(missing_ok=True)
            self._drop_rotation_files()
            return
        try:
            state = json.loads(rotation.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
        if next_private.exists():
            self._next = _read_key(next_private)
            moved = state.get("moved", []) if isinstance(state, dict) else []
            self._moved = {str(m) for m in moved if isinstance(m, str)}
            if not (self._dir / (NEXT_NAME + ".pub")).exists():
                write_atomic(self._dir / (NEXT_NAME + ".pub"), self._next.public_line + "\n")
            return
        if isinstance(state, dict) and state.get("new_fingerprint") == self._current.fingerprint:
            self._drop_rotation_files()  # a finish cut short after its replace: the .pub is already fixed
            return
        log.warning(
            "The next app key is gone: its rotation is dropped (routers moved to it must be added again)"
        )
        self._drop_rotation_files()
