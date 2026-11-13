"""Restore a backup and reset to defaults (v0.6c plan D11, D12): the lines a preview shows, and the proof
that a restore took. The job that waits for the router is the reboot's (reboot.py, SystemService)."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import re
import socket
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.writes import upload_line
from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.store.routers import RouterRecord
from openwrtgui.system import commands as s
from openwrtgui.system.archive import ArchiveFile, ArchiveInfo
from openwrtgui.system.reboot import reboot_command, reboot_warnings
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show

_PROVABLE = re.compile(r"/[A-Za-z0-9._/@+-]{1,255}")  # the paths file_digests takes
# OpenWrt runs and deletes these at the first boot (sysupgrade -b adds 10_disable_services itself): gone
# after a restore by design (AP2, HW-3 2026-11-13)
_UCI_DEFAULTS = "/etc/uci-defaults/"
_CONFIG_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")  # a config `uci -q show <name>` can be asked about
_LIBUCI_NAME = re.compile(r"cfg[0-9a-f]{6}")  # how libuci names an unnamed section (`uci -X show`)


class RestoreCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    files: tuple[str, ...]
    warnings: tuple[str, ...]
    refusals: tuple[str, ...]


async def router_ipv4(host: str) -> str:
    """The IPv4 address the app reaches a router at: its host when that is an address, else the first IPv4
    the resolver gives for the name; the name as given when it does not resolve (a check then names it)."""
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return host
    return str(found[0][4][0]) if found else host


def restore_lines(name: str, data: bytes) -> list[str]:
    return [upload_line(s.UPLOAD_RESTORE, name, data), s.LIST_RESTORE, s.RESTORE, reboot_command()]


def restore_warnings(router_name: str, created: datetime) -> tuple[str, ...]:
    return (
        f"{router_name}'s settings become the backup's ({created:%Y-%m-%d %H:%M}): every file in it replaces "
        "the router's own",
        *reboot_warnings(router_name),
    )


def proven_configs(info: ArchiveInfo) -> tuple[tuple[str, str], ...]:
    """The archive's configs proven by their settings after the restore: the boot may add to a config (AP2
    stages `network+='lte'` and uci-defaults' `uci commit` keeps it), so its bytes are no proof."""
    return tuple((name, text) for name, text in info.configs if _CONFIG_NAME.fullmatch(name))


def provable(info: ArchiveInfo) -> list[ArchiveFile]:
    """The archive's files whose sha256 the router is asked for after the restore: not the uci-defaults the
    first boot consumes, not the configs proven by their settings."""
    by_settings = {f"/etc/config/{name}" for name, _ in proven_configs(info)}
    return [
        f
        for f in info.files
        if _PROVABLE.fullmatch(f.path) and not f.path.startswith(_UCI_DEFAULTS) and f.path not in by_settings
    ]


def listed_ok(listed: str, info: ArchiveInfo) -> bool:
    """`tar -tzf` on the router lists every file the PC read in the archive."""
    names = {line.strip().lstrip("./").rstrip("/") for line in listed.splitlines() if line.strip()}
    return all(f.path.lstrip("/") in names for f in info.files)


def _as_uci_show(values: dict[str, str]) -> dict[str, str]:
    """Unnamed sections as `uci show` names them (`@type[n]`, n counting every section of the type), whether
    they came as libuci's cfgXXXXXX (`uci -X show`, the simulator) or already so."""
    renamed: dict[str, str] = {}
    counts: dict[str, int] = {}
    for key, kind in values.items():
        config, _, section = key.partition(".")
        if not section or "." in section:
            continue
        index = counts.get(kind, 0)
        counts[kind] = index + 1
        if _LIBUCI_NAME.fullmatch(section):
            renamed[key] = f"{config}.@{kind}[{index}]"
    out: dict[str, str] = {}
    for key, value in values.items():
        head = ".".join(key.split(".")[:2])
        out[renamed.get(head, head) + key[len(head) :]] = value
    return out


def _missing(expected: dict[str, str], got: dict[str, str]) -> list[str]:
    """The backup's settings not on the router. A list holds when every item the backup has is there: the boot
    may add items (lists and options alike read as space-joined words)."""
    return [
        key
        for key, want in expected.items()
        if key not in got or (got[key] != want and Counter(want.split()) - Counter(got[key].split()))
    ]


async def differing(
    t: Transport, files: list[ArchiveFile], configs: tuple[tuple[str, str], ...] = ()
) -> list[str]:
    """The files whose sha256 on the router is not the archive's (a missing file differs too), then the
    configs whose settings from the backup are not all in the router's `uci -q show` (a missing config
    differs)."""
    out: list[str] = []
    if files:
        result = await t.run(s.file_digests([f.path for f in files]))
        got: dict[str, str] = {}
        for line in result.stdout.splitlines():
            digest, _, path = line.partition("  ")
            if path:
                got[path.strip()] = digest.strip()
        out = [f.path for f in files if got.get(f.path) != f.sha256]
    for name, text in configs:
        shown = await t.run(f"uci -q show {name}")
        expected = _as_uci_show(parse_uci_file(name, text))
        if not shown.ok or _missing(expected, _as_uci_show(parse_uci_show(shown.stdout))):
            out.append(f"/etc/config/{name}")
    return out


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
