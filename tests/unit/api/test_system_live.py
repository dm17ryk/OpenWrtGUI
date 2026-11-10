"""The System screen's live charts: load, bytes per second per interface and the connection count every 3 s
while the Status tab is open (v0.6b D3); a missed read is a gap, never a stop."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apiconst import BASE, TOKEN, WS
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openwrtgui.app import create_app
from openwrtgui.context import AppContext
from openwrtgui.system import commands as s
from openwrtgui.system.sampler import SystemSampler
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def _system(ctx: AppContext):  # type: ignore[no-untyped-def]
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.system is not None
    return t.state.system


async def test_two_ticks_give_load_rates_and_connections(ctx: AppContext) -> None:
    clock = Clock()
    sampler = SystemSampler("ap2", pool=ctx.pool, routers=ctx.routers, clock=clock)
    first = await sampler.tick()
    assert first["type"] == "system"
    sample = first["sample"]
    assert (sample.load1, sample.connections, sample.rates) == (0.16, 42, {})  # rates need two samples
    sim = await _system(ctx)
    sim._start -= 3.0  # the simulated counters move on by 3 s
    clock.now += timedelta(seconds=3)
    second = (await sampler.tick())["sample"]
    rx, tx = second.rates["br-lan"]
    # the simulator's br-lan rate in bytes per second (its counters run on real time: a few ms slip in)
    assert 11900 < rx < 12300 and 29700 < tx < 30600


async def test_a_missed_read_is_a_gap(ctx: AppContext) -> None:
    sim = await _system(ctx)
    real = sim.answer
    failed = {"n": 0}

    def once(command: str) -> CommandResult | None:
        if command == s.LIVE and failed["n"] == 0:
            failed["n"] += 1
            return CommandResult(command, "", "Request canceled\n", 1)
        return real(command)

    sim.answer = once  # type: ignore[method-assign]
    sampler = SystemSampler("ap2", pool=ctx.pool, routers=ctx.routers, interval_s=0.0)
    queue = sampler.subscribe()
    try:
        first = await asyncio.wait_for(queue.get(), 5)
        second = await asyncio.wait_for(queue.get(), 5)
        assert first == {"type": "system-idle", "reason": "No answer from the router"}
        assert second["type"] == "system" and sampler.running
    finally:
        sampler.unsubscribe(queue)
    assert not sampler.running


async def test_connections_capped_and_missing_table(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    got = await authed.get("/api/routers/ap2/system/connections")
    assert got.status_code == 200
    body = got.json()
    assert body["note"] is None and 0 < len(body["rows"]) <= 500
    assert any(r["state"] == "ESTABLISHED" and r["dport"] == 22 for r in body["rows"])
    sim = await _system(ctx)
    real = sim.answer

    def no_conntrack(command: str) -> CommandResult | None:
        if command == s.CONNTRACK:
            return CommandResult(command, "", "head: /proc/net/nf_conntrack: No such file or directory\n", 1)
        return real(command)

    sim.answer = no_conntrack  # type: ignore[method-assign]
    missing = (await authed.get("/api/routers/ap2/system/connections")).json()
    assert missing == {
        "rows": [],
        "note": "The connection table is not available: nf_conntrack is not loaded",
    }


def test_system_ws_streams_samples(ctx: AppContext) -> None:
    tc = TestClient(create_app(ctx), base_url=BASE)
    with tc.websocket_connect(f"{WS}/ws/system/ap2?t={TOKEN}") as ws:
        first: dict[str, Any] = ws.receive_json()
        assert first["type"] == "system" and first["sample"]["load1"] == 0.16
    with (
        pytest.raises(WebSocketDisconnect) as missing,
        tc.websocket_connect(f"{WS}/ws/system/nope?t={TOKEN}") as ws,
    ):
        ws.receive_json()
    assert missing.value.code == 4404
