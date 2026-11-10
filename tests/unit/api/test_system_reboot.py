"""System › Reboot in the simulator: armed by the router-side timer, proven by a fresh uptime (v0.6b D8)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui import simsystem
from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system.reboot import RebootBusy, RebootJob

ARM = (
    "mkdir -p /tmp/owg && start-stop-daemon -S -b -m -p /tmp/owg/reboot.pid -x /bin/sh -- -c "
    "'sleep 2; reboot; rm -f /tmp/owg/reboot.*'"
)


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simsystem, "REBOOT_S", 0.5)


async def wait_job(ctx: AppContext, router_id: str = "ap2", timeout: float = 20.0) -> RebootJob:
    for _ in range(int(timeout / 0.1)):
        job = ctx.system.reboot_job(router_id)
        if job is not None and job.phase in ("back", "not back"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"reboot still running: {ctx.system.reboot_job(router_id)}")


async def test_reboot_preview_is_the_timer_and_its_warnings(ctx: AppContext) -> None:
    plan = await ctx.system.plan_reboot("ap2")
    assert plan.lines == (ARM,)
    assert plan.warnings == (
        "AP2 · office is offline for about 60-90 s while it restarts",
        "LTE and Wi-Fi come back with the router; the LuCI bridge and the terminal reconnect by themselves",
    )


async def test_reboot_proven_by_a_fresh_uptime(ctx: AppContext) -> None:
    ctx.system.every_s = 0.2
    before = await ctx.system.overview("ap2")
    plan = await ctx.system.plan_reboot("ap2")
    job = await ctx.system.start_reboot("ap2", plan.digest)
    assert job.phase == "armed" and job.uptime_s is None
    done = await wait_job(ctx)
    assert done.phase == "back", done
    assert done.uptime_s is not None and done.uptime_s < 10.0
    assert done.detail is not None and done.detail.startswith("AP2 · office is back after ")
    assert ARM in [e.command for e in ctx.audit.query()]
    after = await ctx.system.overview("ap2")
    assert after.uptime_s is not None and before.uptime_s is not None and after.uptime_s < before.uptime_s


async def test_reboot_that_does_not_come_back(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simsystem, "REBOOT_S", 1e9)
    now = [1000.0]
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds: float) -> None:
        if now[0] == 1000.0:
            await real_sleep(2.3)  # the router-side timer fires: AP2 goes down and stays down
        now[0] += seconds
        await real_sleep(0)

    monkeypatch.setattr(ctx.system, "_sleep", fake_sleep)
    monkeypatch.setattr(ctx.system, "_monotonic", lambda: now[0])
    plan = await ctx.system.plan_reboot("ap2")
    await ctx.system.start_reboot("ap2", plan.digest)
    done = await wait_job(ctx)
    assert (done.phase, done.uptime_s) == ("not back", None)
    assert done.error == "AP2 · office is not back after 300 s: check its power and LEDs, then Reconnect"


async def test_one_reboot_at_a_time(ctx: AppContext) -> None:
    ctx.system.every_s = 0.2
    plan = await ctx.system.plan_reboot("ap2")
    await ctx.system.start_reboot("ap2", plan.digest)
    with pytest.raises(RebootBusy, match="^AP2 · office is already rebooting$"):
        await ctx.system.start_reboot("ap2", plan.digest)
    await wait_job(ctx)


async def test_reboot_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    plan = await ctx_guard_live.system.plan_reboot("ap2")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.start_reboot("ap2", plan.digest)
    assert ctx_guard_live.system.reboot_job("ap2") is None


async def test_reboot_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.system.every_s = 0.2
    base = "/api/routers/ap2/system/reboot"
    assert (await authed.get(base)).json() is None
    preview = await authed.post(f"{base}/preview")
    assert preview.status_code == 200 and preview.json()["lines"] == [ARM]
    stale = await authed.post(f"{base}/start", json={"digest": "0" * 16})
    assert stale.status_code == 409
    started = await authed.post(f"{base}/start", json={"digest": preview.json()["digest"]})
    assert (started.status_code, started.json()["phase"]) == (200, "armed")
    again = await authed.post(f"{base}/start", json={"digest": preview.json()["digest"]})
    assert again.status_code == 409
    await wait_job(ctx)
    assert (await authed.get(base)).json()["phase"] == "back"
