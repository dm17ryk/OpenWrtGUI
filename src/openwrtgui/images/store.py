"""Imported images and their profiles: <data>/profiles/<board>/<revision>-<sha256[:12] or rom>/.

Each folder holds profile.json and, for an imported image, a copy of the image (decision D2), so a flash and
the firmware check never depend on a file the user may move.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from openwrtgui.images.profile import Profile, ProfileKey, build_profile
from openwrtgui.store import write_atomic

PROFILE_FILE = "profile.json"
IMAGE_FILE = "image.bin"
_BOARD = re.compile(r"[^A-Za-z0-9._,-]")


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _folder(self, key: ProfileKey) -> Path:
        return self._root / _BOARD.sub("_", key.board) / key.folder

    def list(self) -> list[Profile]:
        out: list[Profile] = []
        for path in sorted(self._root.glob(f"*/*/{PROFILE_FILE}")):
            try:
                out.append(Profile.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, ValidationError):
                continue  # a damaged profile is left out; importing the image again replaces it
        return sorted(out, key=lambda p: (p.key.board, p.key.revision, p.source, p.key.sha256))

    def get(self, key: ProfileKey) -> Profile | None:
        return next((p for p in self.list() if p.key == key), None)

    def import_image(self, data: bytes, name: str, now: datetime) -> Profile:
        profile = build_profile(data, name, now)
        if any(p.key.sha256 == profile.key.sha256 for p in self.list()):
            raise ValueError(f"This image is already imported ({profile.key.label})")
        folder = self._folder(profile.key)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{IMAGE_FILE}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, folder / IMAGE_FILE)
        write_atomic(folder / PROFILE_FILE, profile.model_dump_json(indent=1))
        return profile

    def save(self, profile: Profile) -> None:
        folder = self._folder(profile.key)
        folder.mkdir(parents=True, exist_ok=True)
        write_atomic(folder / PROFILE_FILE, profile.model_dump_json(indent=1))

    def delete(self, key: ProfileKey) -> None:
        folder = self._folder(key)
        if not folder.is_dir():
            raise ValueError(f"No imported image or profile {key.label}")
        shutil.rmtree(folder)

    def image_bytes(self, key: ProfileKey) -> bytes:
        profile = self.get(key)
        if profile is None or profile.source != "image":
            raise ValueError("Flash needs the image file: import it in Settings › Images")
        path = self._folder(key) / IMAGE_FILE
        data = path.read_bytes() if path.is_file() else b""
        if hashlib.sha256(data).hexdigest() != key.sha256:
            raise ValueError(f"{profile.image_name} changed on disk since it was imported; import it again")
        return data

    def match(self, board: str, revision: str) -> Profile | None:
        found = [p for p in self.list() if p.key.board == board and p.key.revision == revision]
        found.sort(key=lambda p: (p.source == "image", p.built_at), reverse=True)
        return found[0] if found else None
