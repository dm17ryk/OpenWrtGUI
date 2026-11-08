"""The firmware check (decision D4): the firmware partition's first bytes hashed on the router, compared with
the same bytes of the image (a flash writes the kernel and squashfs unchanged; rootfs_data starts after)."""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict

_MTD = re.compile(r'mtd(\d+): \S+ \S+ "([^"]+)"')


class FirmwareCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    matches: bool | None
    detail: str
    image_sha256: str | None
    router_sha256: str | None
    read_s: float | None


def parse_proc_mtd(text: str) -> dict[str, int]:
    """`cat /proc/mtd` → partition name → mtd index."""
    return {m.group(2): int(m.group(1)) for m in _MTD.finditer(text)}


def image_prefix_sha256(data: bytes, length: int) -> str:
    return hashlib.sha256(data[:length]).hexdigest()
