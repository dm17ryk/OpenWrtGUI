"""Flash without keeping settings (decision D6): the router entry waits for Add again, and the wizard expects
the new host key only when the board and revision it reads match the flashed image."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui import simimage
from openwrtgui.context import AppContext
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.store.routers import ReflashPending
from openwrtgui.transport.base import Unreachable

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (FIX / "mini-r35692.bin").read_bytes()
NEWER = (FIX / "mini-r35700.bin").read_bytes()
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
REQ = FlashRequest(
    board="dlink,dwr-921-c3-uboot",
    revision="r35700-0c0ffee000",
    sha256=hashlib.sha256(NEWER).hexdigest(),
    keep_settings=False,
    isolated=True,
)


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simimage, "REBOOT_S", 0.3)


async def _flash_ap1(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI, "mini-r35692.bin", NOW)
    ctx.profiles.import_image(NEWER, "mini-r35700.bin", NOW)
    plan = await ctx.flash.plan("ap1", REQ)
    await ctx.flash.start("ap1", REQ, plan.digest)
    for _ in range(100):
        job = ctx.flash.job("ap1")
        if job is not None and job.phase in ("done", "failed"):
            break
        await asyncio.sleep(0.1)


async def _reboot(ctx: AppContext) -> None:
    """The router-side timer starts sysupgrade 2 s after arming, at the router's next command."""
    sim = ctx.onboard._connector  # type: ignore[attr-defined]
    await asyncio.sleep(2.2)
    try:  # reaching the router runs its due timer: sysupgrade starts and the connection is refused
        t = await sim.connect("192.168.1.1", 22, password=None, key_paths=[Path("k")])
        await t.run("true")
    except Unreachable:
        pass
    await asyncio.sleep(0.5)


async def test_no_keep_flash_marks_the_router(ctx: AppContext) -> None:
    await _flash_ap1(ctx)
    job = ctx.flash.job("ap1")
    assert job is not None and job.phase == "done", job
    assert job.detail is not None and job.detail.startswith("Reflashed without settings")
    pending = ctx.routers.get("ap1").reflashed  # type: ignore[union-attr]
    assert pending is not None
    assert (pending.board, pending.revision) == ("dlink,dwr-921-c3-uboot", "r35700-0c0ffee000")
    assert any("sysupgrade -n /tmp/owg/fw-" in e.command for e in ctx.audit.query())
    assert (await ctx.discovery.summary("ap1")).reflash_pending is True  # before its timer starts sysupgrade


async def test_wizard_expects_the_new_key_after_a_matching_reflash(ctx: AppContext) -> None:
    sim = ctx.onboard._connector  # type: ignore[attr-defined]
    ctx.host_keys.pin("192.168.1.1", 22, await sim.fetch_host_key("192.168.1.1", 22))
    await _flash_ap1(ctx)
    await _reboot(ctx)
    view = await ctx.onboard.start("192.168.1.1")
    assert view.changed_from is not None
    assert view.expected_reflash is True
    trusted = await ctx.onboard.trust(view.sid, view.host_key.fingerprint)  # type: ignore[union-attr]
    record = await ctx.onboard.finish(trusted.sid, "AP1 · bench", {})
    assert record.id == "ap1"
    assert record.reflashed is None


async def test_wizard_blocks_a_key_change_that_does_not_match(ctx: AppContext) -> None:
    sim = ctx.onboard._connector  # type: ignore[attr-defined]
    ctx.host_keys.pin("192.168.1.1", 22, await sim.fetch_host_key("192.168.1.1", 22))
    await _flash_ap1(ctx)
    rec = ctx.routers.get("ap1")
    assert rec is not None
    other = ReflashPending(board="dlink,dwr-921-c3-uboot", revision="r99999-ffffffffff", at=NOW)
    ctx.routers.upsert(rec.model_copy(update={"reflashed": other}))
    await _reboot(ctx)
    view = await ctx.onboard.start("192.168.1.1")
    assert view.changed_from is not None
    assert view.expected_reflash is False
