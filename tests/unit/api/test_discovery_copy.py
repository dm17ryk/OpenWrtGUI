"""Discovery copies: files added after flashing, between simulated routers; the reflash checklist."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.discovery.copy import CopyRequest
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.transport.fake import ReplayTransport

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def import_mini(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI.read_bytes(), "mini-r35692.bin", NOW)


async def _router(ctx: AppContext, router_id: str) -> ReplayTransport:
    t = await ctx.pool.get(ctx.routers.get(router_id))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport)
    return t


async def test_copy_between_sim_routers(ctx: AppContext) -> None:
    req = CopyRequest(paths=("/root/notes.txt",), target="ap1")
    plan = await ctx.discovery.plan_copy("ap2", req)
    assert plan.lines == (
        "mkdir -p /root && cat > /root/notes.txt  # stdin: ap2:/root/notes.txt (12 B, sha256 293dea8a158f)",
        "chmod 0644 /root/notes.txt",
        "sha256sum /root/notes.txt",
    )
    result = await ctx.discovery.apply_copy("ap2", req, plan.digest)
    assert (result.applied, result.verified, result.error) == (True, True, None)
    assert [c.name for c in result.checks] == ["file /root/notes.txt"]
    ap1 = await _router(ctx, "ap1")
    assert (await ap1.run("cat /root/notes.txt")).stdout == "bench notes\n"
    assert any("# stdin: ap2:/root/notes.txt" in e.command for e in ctx.audit.query())


async def test_copy_refuses_what_is_not_in_the_overlay(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match=r"^/etc/openwrt_release is not in AP2 · office's overlay"):
        await ctx.discovery.plan_copy("ap2", CopyRequest(paths=("/etc/openwrt_release",), target="ap1"))
    with pytest.raises(ValueError, match=r"is the router's own key or password"):
        await ctx.discovery.plan_copy(
            "ap2", CopyRequest(paths=("/etc/owg/nft/inet-owg_test.nft",), target="ap1")
        )


async def test_copy_limits(ctx: AppContext) -> None:
    ap2 = await _router(ctx, "ap2")
    await ap2.upload("mkdir -p /root && cat > /root/big.bin", b"x" * (2 * 2**20))
    with pytest.raises(ValueError, match=r"^/root/big\.bin is 2 MB; a copy takes files up to 1 MB$"):
        await ctx.discovery.plan_copy("ap2", CopyRequest(paths=("/root/big.bin",), target="ap1"))
    names = tuple(f"/root/m{i}.bin" for i in range(5))
    for name in names:
        await ap2.upload(f"mkdir -p /root && cat > {name}", b"y" * 2**20)
    with pytest.raises(ValueError, match=r"^A copy takes at most 4 MB in all$"):
        await ctx.discovery.plan_copy("ap2", CopyRequest(paths=names, target="ap1"))


async def test_stale_preview(ctx: AppContext) -> None:
    from openwrtgui.wifi.service import PreviewChanged

    req = CopyRequest(paths=("/root/notes.txt",), target="ap1")
    with pytest.raises(PreviewChanged):
        await ctx.discovery.apply_copy("ap2", req, "0000000000000000")


async def test_copy_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    req = CopyRequest(paths=("/root/notes.txt",), target="ap1")
    plan = await ctx_guard_live.discovery.plan_copy("ap2", req)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.discovery.apply_copy("ap2", req, plan.digest)


async def test_checklist_lists_what_a_flash_loses(ctx: AppContext) -> None:
    import_mini(ctx)
    c = await ctx.discovery.save_checklist("ap2")
    assert [f.path for f in c.lost] == ["/etc/owg/nft/inet-owg_test.nft", "/root/notes.txt"]
    notes = c.lost[1]
    assert notes.data is not None
    assert base64.b64decode(notes.data) == b"bench notes\n"
    assert c.profile is not None
    assert ctx.discovery.checklists.latest("ap2") == c
    assert len(list(ctx.data.reflash_dir.glob("ap2-*.json"))) == 1


async def test_copy_back_from_a_checklist(ctx: AppContext) -> None:
    import_mini(ctx)
    c = await ctx.discovery.save_checklist("ap2")
    stamp = c.saved_at.strftime("%Y%m%d-%H%M%S")
    req = CopyRequest(paths=("/root/notes.txt",), target="ap1", from_checklist=stamp)
    plan = await ctx.discovery.plan_copy("ap2", req)
    assert (await ctx.discovery.apply_copy("ap2", req, plan.digest)).verified
    with pytest.raises(ValueError, match=r"^No reflash checklist 19990101-000000 for AP2 · office$"):
        await ctx.discovery.plan_copy("ap2", req.model_copy(update={"from_checklist": "19990101-000000"}))


async def test_copy_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    body = {"paths": ["/root/notes.txt"], "target": "ap1"}
    preview = await authed.post("/api/routers/ap2/discovery/copy/preview", json=body)
    assert preview.status_code == 200
    applied = await authed.post(
        "/api/routers/ap2/discovery/copy/apply", json=body | {"digest": preview.json()["digest"]}
    )
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
    saved = await authed.post("/api/routers/ap2/discovery/checklist")
    assert saved.status_code == 200
    listed = (await authed.get("/api/routers/ap2/discovery/checklists")).json()
    assert listed[0]["lost"] == ["/etc/owg/nft/inet-owg_test.nft", "/root/notes.txt"]
