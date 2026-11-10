"""Restore a backup and reset to defaults (v0.6c plan D11, D12): the lines a preview shows, and the proof
that a restore took. The job that waits for the router is the reboot's (reboot.py, SystemService)."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.writes import upload_line
from openwrtgui.store.routers import RouterRecord
from openwrtgui.system import commands as s
from openwrtgui.system.archive import ArchiveFile, ArchiveInfo
from openwrtgui.system.reboot import reboot_command, reboot_warnings
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

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


# ---------------------------------------------------------------- reset to defaults (D12)
RESET_LIMIT_S = 120.0  # firstboot erases the overlay and reboots within seconds of the timer
FACTORY_ADDRESS = "192.168.1.1"


def reset_warnings(router_name: str, clash: str | None) -> tuple[str, ...]:
    first = (
        f"{router_name} erases every setting and comes back as {FACTORY_ADDRESS} with no password and a new "
        "host key"
    )
    if clash:
        first += f": that address clashes with {clash}"
    return (first, f"Connect {router_name} alone to this PC before you go on, then add it again")


def reset_done(router_name: str) -> str:
    return f"{router_name} is resetting to defaults: it comes back as {FACTORY_ADDRESS} with no password"


def not_reset(router_name: str, limit_s: float) -> str:
    return f"{router_name} still answers after {limit_s:g} s: it did not reset. Check it, then try again"


async def wait_until_gone(
    pool: ConnectionPool,
    rec: RouterRecord,
    *,
    armed_at: float,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
    every_s: float,
    limit_s: float = RESET_LIMIT_S,
) -> bool:
    """True once a new login at the router's address fails (firstboot took it away), False after limit_s."""
    await pool.drop(rec.id)
    while clock() - armed_at < limit_s:
        await sleep(every_s)
        try:
            t = await pool.fresh(rec)
        except TransportError:
            return True
        try:
            if not (await t.run("true")).ok:
                return True
        except TransportError:
            return True
        finally:
            with contextlib.suppress(TransportError):
                await t.close()
    return False
