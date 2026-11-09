"""System › Backup in the simulator: `sysupgrade -b -` saved in the data folder, listed, downloaded (D9)."""

from __future__ import annotations

import gzip
import io
import re
import tarfile

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.simsystem import SimSystem
from openwrtgui.transport.base import TransportError
from openwrtgui.transport.fake import Unreachable

NAME = re.compile(r"ap2-\d{8}-\d{6}\.tar\.gz")


def _audit(ctx: AppContext) -> list[str]:
    return [e.command for e in ctx.audit.query()]


async def test_a_backup_is_saved_listed_and_audited_as_one_line(ctx: AppContext) -> None:
    saved = await ctx.system.create_backup("ap2")
    assert NAME.fullmatch(saved.name) and saved.size > 0
    path = ctx.system.backup_path("ap2", saved.name)
    assert path == ctx.data.root / "backups" / "ap2" / saved.name
    data = path.read_bytes()
    assert len(data) == saved.size and data[:2] == b"\x1f\x8b"
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))) as tar:
        assert "etc/config/system" in tar.getnames()
    assert [b.name for b in await ctx.system.backups("ap2")] == [saved.name]
    assert f"sysupgrade -b -  # saved to {saved.name}" in _audit(ctx)
    assert not [p for p in path.parent.iterdir() if p.name != saved.name]  # no part file left


async def test_backup_during_a_run(ctx_guard_live: AppContext) -> None:
    saved = await ctx_guard_live.system.create_backup("ap2")
    assert saved.size > 0 and f"sysupgrade -b -  # saved to {saved.name}" in _audit(ctx_guard_live)


async def test_an_empty_archive_is_refused_and_not_kept(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SimSystem, "backup", lambda self: b"")
    with pytest.raises(ValueError, match="^AP2 · office gave no backup: an empty archive$"):
        await ctx.system.create_backup("ap2")
    assert await ctx.system.backups("ap2") == []


async def test_a_lost_connection_leaves_no_part_file(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lost(self: SimSystem, command: str) -> bytes:
        raise Unreachable("the connection was lost")

    monkeypatch.setattr(SimSystem, "stream", lost)
    with pytest.raises(TransportError):
        await ctx.system.create_backup("ap2")
    folder = ctx.data.root / "backups" / "ap2"
    assert not folder.exists() or list(folder.iterdir()) == []


async def test_unknown_names_are_not_served(ctx: AppContext) -> None:
    await ctx.system.create_backup("ap2")
    for name in ("../routers.json", "ap2-20260101-000000.tar.gz", "x"):
        with pytest.raises(LookupError):
            ctx.system.backup_path("ap2", name)


async def test_backup_endpoints_download_byte_for_byte(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    base = "/api/routers/ap2/system/backups"
    assert (await authed.get(base)).json() == []
    made = await authed.post("/api/routers/ap2/system/backup")
    assert made.status_code == 200
    name = made.json()["name"]
    listed = await authed.get(base)
    assert [b["name"] for b in listed.json()] == [name]
    got = await authed.get(f"{base}/{name}")
    assert got.status_code == 200 and got.headers["content-type"] == "application/gzip"
    assert got.content == ctx.system.backup_path("ap2", name).read_bytes()
    assert (await authed.get(f"{base}/..%2Frouters.json")).status_code == 404
    assert (await authed.get(f"{base}/ap2-20260101-000000.tar.gz")).status_code == 404
    commands = _audit(ctx)
    assert all("\x1f\x8b" not in c and "etc/config" not in c for c in commands)
