"""The Recover endpoints (spec 4.2): preview, start with the preview's digest, the job, stop."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.transport.fake import ReplayTransport

BASE = "/api/routers/ap2/lte/recover"


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext) -> None:
    ctx.lte.poll_s = 0.0
    ctx.lte.readback_s = 0.0
    ctx.lte_recover.autoconnect_gap_s = 0.0


async def _modem(ctx: AppContext):  # type: ignore[no-untyped-def]
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


async def test_preview_start_job_round_trip(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    assert (await authed.get(BASE)).json() is None
    (await _modem(ctx)).connected = False
    preview = await authed.post(f"{BASE}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert set(body) == {"lines", "warnings", "digest"} and body["lines"]
    started = await authed.post(BASE, json={"digest": body["digest"]})
    assert started.status_code == 200 and started.json()["phase"] == "running"
    await ctx.lte_recover.finished("ap2")
    job = (await authed.get(BASE)).json()
    assert (job["phase"], job["detail"]) == ("recovered", "LTE works again after: Reconnect.")
    assert [r["name"] for r in job["rungs"]][1] == "Reconnect"


async def test_a_stale_digest_is_409(authed: httpx.AsyncClient) -> None:
    refused = await authed.post(BASE, json={"digest": "0000000000000000"})
    assert refused.status_code == 409


async def test_a_second_start_is_409(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    ctx.lte._sleep = slow  # type: ignore[assignment]
    ctx.lte.poll_s = 1.0
    (await _modem(ctx)).wedged = True
    digest = (await authed.post(f"{BASE}/preview")).json()["digest"]
    assert (await authed.post(BASE, json={"digest": digest})).status_code == 200
    again = await authed.post(BASE, json={"digest": digest})
    assert (again.status_code, again.json()["detail"]) == (409, "LTE recovery runs on AP2 · office")
    stopped = await authed.post(f"{BASE}/stop")
    assert stopped.status_code == 200
    gate.set()
    await ctx.lte_recover.finished("ap2")
    assert (await authed.get(BASE)).json()["phase"] == "stopped"


async def test_stop_without_a_job_is_null(authed: httpx.AsyncClient) -> None:
    stopped = await authed.post(f"{BASE}/stop")
    assert (stopped.status_code, stopped.json()) == (200, None)


async def test_a_harness_run_is_423(authed_guard_live: httpx.AsyncClient) -> None:
    preview = await authed_guard_live.post(f"{BASE}/preview")
    assert preview.status_code == 200  # reads only
    refused = await authed_guard_live.post(BASE, json={"digest": preview.json()["digest"]})
    assert refused.status_code == 423
