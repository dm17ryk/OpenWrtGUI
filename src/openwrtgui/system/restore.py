"""Restore a backup and reset to defaults (v0.6c plan D11, D12): the lines a preview shows, and the proof
that a restore took. The job that waits for the router is the reboot's (reboot.py, SystemService)."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.writes import upload_line
from openwrtgui.system import commands as s
from openwrtgui.system.archive import ArchiveFile, ArchiveInfo
from openwrtgui.system.reboot import reboot_command, reboot_warnings
from openwrtgui.transport.base import Transport

_PROVABLE = re.compile(r"/[A-Za-z0-9._/@+-]{1,255}")  # the paths file_digests takes


class RestoreCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: tuple[str, ...]
    warnings: tuple[str, ...]
    refusals: tuple[str, ...]


def restore_lines(name: str, data: bytes) -> list[str]:
    return [upload_line(s.UPLOAD_RESTORE, name, data), s.LIST_RESTORE, s.RESTORE, reboot_command()]


def restore_warnings(router_name: str, created: datetime) -> tuple[str, ...]:
    return (
        f"{router_name}'s settings become the backup's ({created:%Y-%m-%d %H:%M}): every file in it replaces "
        "the router's own",
        *reboot_warnings(router_name),
    )


def provable(info: ArchiveInfo) -> list[ArchiveFile]:
    """The archive's files whose sha256 the router is asked for after the restore."""
    return [f for f in info.files if _PROVABLE.fullmatch(f.path)]


def listed_ok(listed: str, info: ArchiveInfo) -> bool:
    """`tar -tzf` on the router lists every file the PC read in the archive."""
    names = {line.strip().lstrip("./").rstrip("/") for line in listed.splitlines() if line.strip()}
    return all(f.path.lstrip("/") in names for f in info.files)


async def differing(t: Transport, files: list[ArchiveFile]) -> list[str]:
    """The files whose sha256 on the router is not the archive's (a missing file differs too)."""
    if not files:
        return []
    result = await t.run(s.file_digests([f.path for f in files]))
    got: dict[str, str] = {}
    for line in result.stdout.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            got[path.strip()] = digest.strip()
    return [f.path for f in files if got.get(f.path) != f.sha256]
