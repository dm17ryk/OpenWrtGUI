"""The list of routers the app knows (routers.json)."""

from __future__ import annotations

import builtins
import json
import re
from collections.abc import Collection
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from openwrtgui.store import write_atomic


class RouterRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    host: str
    port: int = 22
    username: str = "root"
    auth: Literal["key", "none"]
    # A key this PC already had and the router already trusted; None means the app's own key.
    key_path: str | None = None
    port_labels: dict[int, str] = {}
    added_at: datetime


_LIST = TypeAdapter(list[RouterRecord])


def router_key_paths(record: RouterRecord, app_key_path: Path) -> list[Path]:
    return [Path(record.key_path)] if record.key_path else [app_key_path]


def make_router_id(name: str, existing: Collection[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "router"
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


class RouterStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[RouterRecord]:
        if not self.path.exists():
            return []
        return _LIST.validate_json(self.path.read_text(encoding="utf-8"))

    def get(self, router_id: str) -> RouterRecord | None:
        return next((r for r in self.list() if r.id == router_id), None)

    def upsert(self, record: RouterRecord) -> None:
        records = [r for r in self.list() if r.id != record.id]
        existing = [r.id for r in self.list()]
        if record.id in existing:
            records.insert(existing.index(record.id), record)
        else:
            records.append(record)
        self._write(records)

    def remove(self, router_id: str) -> bool:
        records = self.list()
        kept = [r for r in records if r.id != router_id]
        if len(kept) == len(records):
            return False
        self._write(kept)
        return True

    def _write(self, records: builtins.list[RouterRecord]) -> None:
        data = [r.model_dump(mode="json") for r in records]
        write_atomic(self.path, json.dumps(data, indent=2, ensure_ascii=False))
