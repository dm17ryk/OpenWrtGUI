"""Frame analysis on the monitor interface (v0.7 plan Task 9, D12), in the simulator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.rf.air import FRAME_WINDOW, MONITOR_FLAGS
from openwrtgui.rf.frames_service import FrameAnalyzer, FrameState
from openwrtgui.simair import SimAir
from openwrtgui.simulator import SIM_GUARD_ENV
from openwrtgui.simwifi import SimWifi
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.wifi.model import ChannelSelection, RadioRequest
from openwrtgui.wifi.monitor import DEL, add_command

Published = list[dict[str, Any]]


async def _fast(_: float) -> None:
    await asyncio.sleep(0)


def _analyzer(ctx: AppContext, router_id: str, published: Published, **kw: Any) -> FrameAnalyzer:
    return FrameAnalyzer(
        router_id,
        "radio0",
        pool=ctx.pool,
        routers=ctx.routers,
        guard=ctx.guard,
        audit=ctx.audit,
        monitors=ctx.wifi.monitors,
        publish=published.append,
        sleep=_fast,
        **kw,
    )


async def _until(check: Callable[[], bool]) -> None:
    for _ in range(500):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError("did not happen")


def _audit(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def _start(a: FrameAnalyzer) -> FrameState:
    return await a.start((await a.preview()).digest)


async def test_frames_start_publishes_windows(ctx: AppContext) -> None:
    published: Published = []
    a = _analyzer(ctx, "ap1", published)
    plan = await a.preview()
    assert MONITOR_FLAGS in plan.lines and any(FRAME_WINDOW in line for line in plan.lines)
    assert plan.warnings and "Costs router CPU" in plan.warnings[0]
    await a.start(plan.digest)
    await _until(lambda: a.state().windows >= 2)
    state = await a.stop()
    assert not state.running and state.error is None and state.fcs_reported
    assert state.totals is not None and state.last is not None
    assert state.totals.rx.frames == 40 * state.windows and state.totals.tx.frames == 60 * state.windows
    assert all(m["type"] == "frames" for m in published) and published[-1]["state"] == state
    lines = _audit(ctx)
    assert MONITOR_FLAGS in lines and any(line.startswith("frame analysis: ") for line in lines)
    assert lines[-1] == DEL  # the last holder removed the monitor


async def test_frames_refused_while_parked(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="^radio0 is parked: nothing of its own to analyse$"):
        await _start(_analyzer(ctx, "ap2", []))


async def test_frames_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    a = _analyzer(ctx_guard_live, "ap1", [])
    with pytest.raises(GuardLocked):
        await _start(a)
    assert not a.state().running


async def test_frames_stop_when_guard_goes_live(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    monkeypatch.setenv(SIM_GUARD_ENV, "live")
    ctx.guard.check_local()
    await _until(lambda: not a.state().running)
    assert a.state().error is not None and "dima_night.py" in a.state().error  # type: ignore[operator]
    assert _audit(ctx)[-1] == DEL  # removed although the run is live: cleanup


async def test_frames_stop_when_last_viewer_leaves(ctx: AppContext) -> None:
    sampler = ctx.rf.sampler("ap1", "radio0")
    queue = sampler.subscribe()
    a = ctx.rf.frames("ap1", "radio0")
    await _start(a)
    await _until(lambda: not queue.empty())  # the first window comes through the RF socket's queue
    msg = queue.get_nowait()
    while msg["type"] != "frames":
        msg = await queue.get()
    sampler.unsubscribe(queue)
    for _ in range(50):
        if not a.state().running:
            break
        await asyncio.sleep(0.01)
    assert not a.state().running and a.state().error == "no RF viewer left"


async def test_frames_stop_after_the_limit(ctx: AppContext) -> None:
    a = _analyzer(ctx, "ap1", [], limit_s=0)
    await _start(a)
    await _until(lambda: not a.state().running)
    assert a.state().error == "Stopped after 30 minutes: frame analysis costs router CPU"


async def test_fcs_not_reported_when_flags_refused(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    original = SimAir._one

    def no_fcs(self: SimAir, p: str) -> CommandResult | None:
        if p == MONITOR_FLAGS:
            return CommandResult(p, "", "command failed: Operation not supported (-95)", 161)
        return original(self, p)

    monkeypatch.setattr(SimAir, "_one", no_fcs)
    a = _analyzer(ctx, "ap1", [])
    state = await _start(a)
    assert state.running and not state.fcs_reported
    await a.stop()


async def test_frames_survive_a_step_reload(ctx: AppContext) -> None:
    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    rec = ctx.routers.get("ap1")
    assert rec is not None
    t = await ctx.pool.get(rec)
    assert (await t.run("wifi down radio0; wifi up radio0", timeout=60)).ok  # a step's reload
    seen = a.state().windows
    await _until(lambda: a.state().windows > seen + 1)
    state = await a.stop()
    assert state.note == "monitor added again after a Wi-Fi reload"
    assert state.last is not None and state.last.rx.frames == 40


ADD_AGAIN = add_command("phy0", clear_leftover=False)


async def _rounds(n: int = 60) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def test_flags_set_again_after_an_apply_re_adds_the_monitor(ctx: AppContext) -> None:
    """Review I2: an Apply's beacon check re-adds owgmon0 after the reload (frames still hold it); the frame
    loop then finds it there, and must still set the flags again."""
    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    state = await ctx.wifi.state("ap1")
    radio = state.radios[0]
    now = radio.actual.channel if radio.actual else None
    channel = next(c for c in radio.limits.channels if c != now)
    await ctx.wifi.apply("ap1", RadioRequest(radio=radio.name, channels=ChannelSelection.of(channel)))
    lines = _audit(ctx)
    assert ADD_AGAIN in lines  # the beacon check put it back
    seen = a.state().windows
    await _until(lambda: a.state().windows > seen + 1)
    await a.stop()
    lines = _audit(ctx)
    last_add = max(i for i, line in enumerate(lines) if line == ADD_AGAIN)
    assert MONITOR_FLAGS in lines[last_add:], lines[last_add:]
    assert a.state().note == "monitor added again after a Wi-Fi reload"


async def test_the_loop_adds_the_monitor_again_only_under_the_write_lock(ctx: AppContext) -> None:
    """Review I3: re-adding owgmon0 and its flags is a write; it waits for an Apply holding the lock."""
    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    rec = ctx.routers.get("ap1")
    assert rec is not None
    t = await ctx.pool.get(rec)
    async with ctx.pool.write_lock("ap1"):
        assert (await t.run("wifi down radio0; wifi up radio0", timeout=60)).ok  # the monitor is gone
        await _rounds()
        assert ADD_AGAIN not in _audit(ctx)
    seen = a.state().windows
    await _until(lambda: a.state().windows > seen)
    await a.stop()
    assert ADD_AGAIN in _audit(ctx)


async def test_a_start_whose_flags_fail_lets_go_of_the_monitor(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review I4: the router drops between the monitor's add and its flags; the lease is not kept."""
    original = SimAir._one

    def drop(self: SimAir, p: str) -> CommandResult | None:
        if p == MONITOR_FLAGS:
            raise TransportError("connection lost")
        return original(self, p)

    monkeypatch.setattr(SimAir, "_one", drop)
    a = _analyzer(ctx, "ap1", [])
    with pytest.raises(TransportError):
        await _start(a)
    assert ctx.wifi.monitors.holders("ap1") == ()
    assert _audit(ctx)[-1] == DEL and not a.state().running


async def test_two_starts_at_once_run_one_analysis(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    original = ReplayTransport.run

    async def yielding(self: ReplayTransport, *args: Any, **kwargs: Any) -> CommandResult:
        await asyncio.sleep(0)  # an SSH round trip: the other Start runs meanwhile
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ReplayTransport, "run", yielding)
    a = _analyzer(ctx, "ap1", [])
    plan = await a.preview()
    await asyncio.gather(a.start(plan.digest), a.start(plan.digest))
    assert ctx.wifi.monitors.holders("ap1") == ("frames radio0",)
    await a.stop()
    assert ctx.wifi.monitors.holders("ap1") == ()
    assert _audit(ctx).count(DEL) == 1


async def test_a_second_stop_lets_the_first_finish(ctx: AppContext) -> None:
    """Review I4: a second Stop (the last viewer leaving, shutdown) must not cancel the first's cleanup."""
    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    async with ctx.pool.write_lock("ap1"):  # the cleanup waits for the lock
        first = asyncio.ensure_future(a.stop())
        await _rounds()
        second = asyncio.ensure_future(a.stop())
        await _rounds()
    await asyncio.gather(first, second)
    assert ctx.wifi.monitors.holders("ap1") == ()
    assert _audit(ctx)[-1] == DEL and not a.state().running


async def test_frames_that_cannot_remove_the_monitor_say_so(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #59 review: a refused `iw dev owgmon0 del` is tried again, and a monitor left behind is reported."""
    original = SimWifi._one

    def refuse_del(self: SimWifi, p: str) -> CommandResult | None:
        if p == DEL:
            return CommandResult(p, "", "command failed: Device or resource busy (-16)\n", 240)
        return original(self, p)

    a = _analyzer(ctx, "ap1", [])
    await _start(a)
    await _until(lambda: a.state().windows >= 1)
    monkeypatch.setattr(SimWifi, "_one", refuse_del)
    state = await a.stop()
    assert state.error is not None and "owgmon0 is still on AP1" in state.error, state.error
    assert _audit(ctx).count(DEL) == 2


async def test_frames_routes(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap1/rf/radio0/frames"
    assert (await authed.get(base)).json()["running"] is False
    preview = (await authed.post(f"{base}/preview")).json()
    assert preview["lines"] and preview["digest"]
    started = await authed.post(f"{base}/start", json={"digest": preview["digest"]})
    assert started.status_code == 200 and started.json()["running"] is True
    stopped = (await authed.post(f"{base}/stop")).json()
    assert stopped["running"] is False
    stale = await authed.post(f"{base}/start", json={"digest": "0" * 16})
    assert stale.status_code == 409
