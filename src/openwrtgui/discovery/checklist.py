"""Reflash checklists: what a router added after flashing and what a flash would lose, with the lost files'
contents (up to the copy limits) so they can be copied back. <data>/reflash/<router>-<YYYYMMDD-HHMMSS>.json"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from openwrtgui.discovery.copy import SavedFile
from openwrtgui.discovery.overlay import OverlayDiff
from openwrtgui.images.apkdb import Package
from openwrtgui.images.profile import ProfileKey
from openwrtgui.store import write_atomic


class ReflashChecklist(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    saved_at: datetime
    profile: ProfileKey | None
    overlay: OverlayDiff
    packages_added: tuple[Package, ...]
    lost: tuple[SavedFile, ...]

    @property
    def stamp(self) -> str:
        return self.saved_at.strftime("%Y%m%d-%H%M%S")


class ChecklistStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, c: ReflashChecklist) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{c.router_id}-{c.stamp}.json"
        write_atomic(path, c.model_dump_json(indent=1))
        return path

    def list(self, router_id: str) -> list[ReflashChecklist]:
        out: list[ReflashChecklist] = []
        for path in sorted(self._root.glob(f"{router_id}-*.json")):
            try:
                c = ReflashChecklist.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, ValidationError):
                continue
            if c.router_id == router_id:
                out.append(c)
        return sorted(out, key=lambda c: c.saved_at)

    def get(self, router_id: str, stamp: str) -> ReflashChecklist | None:
        return next((c for c in self.list(router_id) if c.stamp == stamp), None)

    def latest(self, router_id: str) -> ReflashChecklist | None:
        found = self.list(router_id)
        return found[-1] if found else None
