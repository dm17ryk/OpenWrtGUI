"""Mount points with block-mount (v1.0a2 D5) on ap4: edit, generate, unmount, mount; AP2 has no
block-mount."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.store.routers import RouterRecord
from openwrtgui.system.fstab import FstabChange


def add_ap4(c: AppContext) -> None:
    c.routers.upsert(
        RouterRecord(
            id="ap4",
            name="AP4 · later image",
            host="192.168.1.6",
            auth="key",
            added_at=datetime(2026, 11, 14, 9, 0),
        )
    )


async def test_the_state_on_ap4(ctx: AppContext) -> None:
    add_ap4(ctx)
    state = await ctx.fstab.state("ap4")
    assert state.block and state.missing == ()
    assert [(e.kind, e.section) for e in state.entries] == [("mount", "cfg02a7f1"), ("swap", "cfg03a7f1")]
    assert [d.dev for d in state.devices] == ["/dev/sda1", "/dev/sda2"]


async def test_a_mount_disabled_previewed_and_applied(ctx: AppContext) -> None:
    add_ap4(ctx)
    state = await ctx.fstab.state("ap4")
    off = FstabChange(entries=[state.entries[0].model_copy(update={"enabled": False}), state.entries[1]])
    plan = await ctx.fstab.plan("ap4", off)
    assert plan.lines == (
        "set -e",
        "uci set fstab.cfg02a7f1.enabled='0'",
        "uci commit fstab",
        "/sbin/block mount",
    )
    result = await ctx.fstab.apply("ap4", off, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert not (await ctx.fstab.state("ap4")).entries[0].enabled


async def test_generate_replaces_the_sections(ctx: AppContext) -> None:
    add_ap4(ctx)
    plan = await ctx.fstab.plan_generate("ap4")
    assert "g=$(uci add fstab global)" in plan.lines and "uci -q delete fstab.cfg02a7f1" in plan.lines
    assert (await ctx.fstab.apply_generate("ap4", plan.digest)).verified
    entries = (await ctx.fstab.state("ap4")).entries
    assert [(e.kind, e.enabled) for e in entries] == [("mount", False), ("swap", False)]


async def test_unmount_and_mount_again(ctx: AppContext) -> None:
    add_ap4(ctx)
    plan = await ctx.fstab.plan_unmount("ap4", "/mnt/usb")
    assert plan.lines == ("umount '/mnt/usb'",)
    assert (await ctx.fstab.apply_unmount("ap4", "/mnt/usb", plan.digest)).verified
    with pytest.raises(ValueError, match="Nothing is mounted at /mnt/usb"):
        await ctx.fstab.plan_unmount("ap4", "/mnt/usb")
    with pytest.raises(ValueError, match="not unmounted here"):
        await ctx.fstab.plan_unmount("ap4", "/overlay")
    assert (await ctx.fstab.plan_mount("ap4")).lines == ("/sbin/block mount",)


async def test_ap2_has_no_block_mount(ctx: AppContext) -> None:
    assert not (await ctx.fstab.state("ap2")).block
    with pytest.raises(ValueError, match="no block-mount"):
        await ctx.fstab.plan("ap2", FstabChange(entries=[]))


async def test_the_api_previews_a_refused_target(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    add_ap4(ctx)
    uuid = "5e1f6c2a-9b0d-4c3e-8f7a-1d2c3b4a5e6f"
    entry = {"section": None, "kind": "mount", "uuid": uuid, "target": "/overlay"}
    refused = await authed.post("/api/routers/ap4/system/fstab/preview", json={"entries": [entry]})
    assert refused.status_code == 422 and "own file system" in refused.text


async def test_an_fstab_change_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    add_ap4(ctx_guard_live)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.fstab.apply_mount("ap4", None)


async def test_a_negative_delay_root_is_a_422(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    """v1.0a2 minor: LuCI's uinteger."""
    add_ap4(ctx)
    r = await authed.post("/api/routers/ap4/system/fstab/preview", json={"settings": {"delay_root": -1}})
    assert r.status_code == 422
