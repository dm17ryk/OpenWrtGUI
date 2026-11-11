"""Reset to defaults (plan Task 15, D12), in the simulator only: `firstboot -r -y` through the router-side
timer, only with the router's name typed and the "alone on this PC" tick; done when the router stops
answering, and its entry gets the "add it again" marker."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system import commands as s
from openwrtgui.system.reboot import RebootJob
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport

NAME = "AP2 · office"


async def wait_job(ctx: AppContext, timeout: float = 20.0) -> RebootJob:
    for _ in range(int(timeout / 0.1)):
        job = ctx.system.reboot_job("ap2")
        if job is not None and job.phase not in ("armed", "waiting"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"still running: {ctx.system.reboot_job('ap2')}")


async def test_reset_preview_and_warnings(ctx: AppContext) -> None:
    plan = await ctx.system.plan_reset("ap2")
    assert plan.lines == (s.firstboot_command(),)
    assert plan.warnings == (
        f"{NAME} erases every setting and comes back as 192.168.1.1 with no password and a new host key: "
        "that address clashes with AP1 · bench",
        f"Connect {NAME} alone to this PC before you go on, then add it again",
    )


@pytest.mark.parametrize(("confirm", "alone"), [("AP2", True), (NAME, False), ("", True)])
async def test_reset_needs_the_router_alone(ctx: AppContext, confirm: str, alone: bool) -> None:
    plan = await ctx.system.plan_reset("ap2")
    with pytest.raises(ValueError, match="Type the router's name"):
        await ctx.system.start_reset("ap2", plan.digest, confirm, alone)
    assert s.firstboot_command() not in [e.command for e in ctx.audit.query()]
    assert ctx.system.reboot_job("ap2") is None


async def test_reset_takes_the_router_away_and_marks_it(ctx: AppContext) -> None:
    ctx.system.every_s = 0.2
    plan = await ctx.system.plan_reset("ap2")
    job = await ctx.system.start_reset("ap2", plan.digest, NAME, True)
    assert (job.kind, job.phase) == ("reset", "armed")
    done = await wait_job(ctx)
    assert done.phase == "reset", done
    assert done.detail == f"{NAME} is resetting to defaults: it comes back as 192.168.1.1 with no password"
    marker = ctx.routers.get("ap2").reflashed  # type: ignore[union-attr]
    assert marker is not None and marker.reason == "reset" and marker.board == "dlink,dwr-921-c3-uboot"
    assert s.firstboot_command() in [e.command for e in ctx.audit.query()]


async def test_reset_that_does_not_go_down(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.access is not None
    real = t.state.access.answer

    def ignoring(command: str) -> CommandResult | None:  # the timer runs firstboot, the router stays up
        return CommandResult(command, "", "", 0) if command == "firstboot -r -y" else real(command)

    t.state.access.answer = ignoring  # type: ignore[method-assign]
    now = [1000.0]

    async def fake_sleep(seconds: float) -> None:
        now[0] += seconds
        await asyncio.sleep(0)

    monkeypatch.setattr(ctx.system, "_sleep", fake_sleep)
    monkeypatch.setattr(ctx.system, "_monotonic", lambda: now[0])
    plan = await ctx.system.plan_reset("ap2")
    await ctx.system.start_reset("ap2", plan.digest, NAME, True)
    done = await wait_job(ctx)
    assert done.phase == "not reset"
    assert done.error == f"{NAME} still answers after 120 s: it did not reset. Check it, then try again"
    assert ctx.routers.get("ap2").reflashed is None  # type: ignore[union-attr]


async def test_reset_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    plan = await ctx_guard_live.system.plan_reset("ap2")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.start_reset("ap2", plan.digest, NAME, True)


async def test_reset_endpoints(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap2/system/reset"
    preview = await authed.post(f"{base}/preview")
    assert preview.status_code == 200
    refused = await authed.post(
        f"{base}/start", json={"digest": preview.json()["digest"], "confirm_name": "x", "alone": True}
    )
    assert refused.status_code == 422
