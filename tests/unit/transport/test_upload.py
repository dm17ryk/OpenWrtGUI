"""Uploads: bytes to a command's stdin in 64 KiB chunks with progress; audited with a stdin comment."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.discovery.commands import OVERLAY_LS, ROM_LS, firmware_hash
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.guard.writes import run_audited_upload, upload_line
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Uploader
from openwrtgui.transport.fake import ReplayTransport


def _guard(live: bool) -> BenchGuard:
    processes = ["dima_night.py"] if live else []
    found = [ProcessInfo(1, ("dima_night.py",), datetime(2026, 11, 8, 9, 0))] if live else []
    g = BenchGuard(GuardWatchList(lock_files=[], processes=processes), lister=lambda: found)
    g.check_local()
    return g


async def test_upload_sends_bytes_and_reports_progress() -> None:
    t = ReplayTransport({})
    assert isinstance(t, Uploader)
    got: list[int] = []
    result = await t.upload("cat > /tmp/owg/x.bin", b"x" * 150_000, got.append)
    assert result.exit_status == 0
    assert t.uploads["cat > /tmp/owg/x.bin"] == b"x" * 150_000
    assert got == [65536, 131072, 150000]


def test_upload_line() -> None:
    assert (
        upload_line("cat > /tmp/a", "a.bin", b"abc")
        == "cat > /tmp/a  # stdin: a.bin (3 B, sha256 ba7816bf8f01)"
    )


async def test_upload_is_audited(tmp_path: Path) -> None:
    t = ReplayTransport({})
    audit = AuditLog(tmp_path)
    result = await run_audited_upload(
        t,
        "cat > /tmp/a",
        b"abc",
        name="a.bin",
        router_id="ap2",
        screen="Discovery",
        guard=_guard(False),
        audit=audit,
    )
    assert result.ok
    (entry,) = audit.query()
    assert entry.command == "cat > /tmp/a  # stdin: a.bin (3 B, sha256 ba7816bf8f01)"
    assert (entry.screen, entry.exit_status) == ("Discovery", 0)


async def test_upload_refused_during_a_run(tmp_path: Path) -> None:
    t = ReplayTransport({})
    with pytest.raises(GuardLocked):
        await run_audited_upload(
            t,
            "cat > /tmp/a",
            b"abc",
            name="a.bin",
            router_id="ap2",
            screen="Discovery",
            guard=_guard(True),
            audit=AuditLog(tmp_path),
        )
    assert t.uploads == {}


@pytest.mark.parametrize(
    "cmd",
    [
        OVERLAY_LS,
        ROM_LS,
        "sysupgrade -l",
        "cat /proc/mtd",
        "cat /proc/meminfo",
        "df -k /tmp",
        "uci show dropbear",
        "head -c 6000 '/rom/usr/sbin/dwr921-portctl'",
        firmware_hash(3, 11255254),
    ],
)
def test_discovery_reads_are_read_only(cmd: str) -> None:
    assert is_read_only_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "find /overlay/upper -exec rm {} +",
        "find /overlay/upper -xdev ! -type d -exec ls -ldn {} + ; reboot",
        "sysupgrade -n /tmp/x",
        "sysupgrade -l /tmp/x",
        "dd if=/tmp/x of=/dev/mtdblock3",
        "dd if=/dev/mtdblock3 bs=65536 count=172 of=/tmp/x 2>/dev/null | head -c 1 | sha256sum",
        "uci show 'a;reboot'",
    ],
)
def test_writes_still_refused(cmd: str) -> None:
    assert not is_read_only_command(cmd)
