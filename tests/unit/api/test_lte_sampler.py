"""The live LTE signal: one sample per tick, missed reads survived, streamed over /ws/lte."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from apiconst import BASE, TOKEN, WS
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openwrtgui.app import create_app
from openwrtgui.context import AppContext
from openwrtgui.lte.sampler import LteSampler
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _sampler(ctx: AppContext, **kwargs: Any) -> LteSampler:
    return LteSampler(
        "ap2", pool=ctx.pool, routers=ctx.routers, locate=ctx.lte.modem_device, clock=lambda: NOW, **kwargs
    )


async def test_two_ticks_give_two_samples(ctx: AppContext) -> None:
    sampler = _sampler(ctx)
    first, second = await sampler.tick(), await sampler.tick()
    assert first["type"] == second["type"] == "lte"
    sample = first["sample"]
    assert (sample.registration, sample.radio, sample.t) == ("registered", "lte", NOW.timestamp())
    assert sample.rsrp is not None and -98 <= sample.rsrp <= -92


async def test_sampler_survives_missed_reads(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    real = t.state.modem.answer
    failed = {"n": 0}

    def canceled_once(command: str) -> CommandResult | None:
        if command.startswith("uqmi") and failed["n"] < 2:  # the serving system and the signal of one tick
            failed["n"] += 1
            return CommandResult(command, "", "Request canceled\n", 1)
        return real(command)

    t.state.modem.answer = canceled_once  # type: ignore[method-assign]
    sampler = _sampler(ctx, interval_s=0.0)
    queue = sampler.subscribe()
    try:
        first = await asyncio.wait_for(queue.get(), 5)
        second = await asyncio.wait_for(queue.get(), 5)
        assert first == {"type": "lte-idle", "reason": "No answer from the modem"}
        assert second["type"] == "lte" and sampler.running
    finally:
        sampler.unsubscribe(queue)
    assert not sampler.running


def test_lte_ws_streams_samples(ctx: AppContext) -> None:
    tc = TestClient(create_app(ctx), base_url=BASE)
    with tc.websocket_connect(f"{WS}/ws/lte/ap2?t={TOKEN}") as ws:
        first: dict[str, Any] = ws.receive_json()
        assert first["type"] == "lte" and first["sample"]["registration"] == "registered"
        assert -98 <= first["sample"]["rsrp"] <= -92
    with (
        pytest.raises(WebSocketDisconnect) as missing,
        tc.websocket_connect(f"{WS}/ws/lte/nope?t={TOKEN}") as ws,
    ):
        ws.receive_json()
    assert missing.value.code == 4404
