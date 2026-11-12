"""The step-through over the API, one radio action at a time, restores after a restart (v0.7 plan Task 12)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx

from openwrtgui.app import create_app
from openwrtgui.context import AppContext
from openwrtgui.system.reboot import RebootJob
from openwrtgui.transport.base import ubus_call
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest
from openwrtgui.wifi.steps import StepRequest, saved_options

W = "/api/routers/ap2/wifi"
MANUAL: dict[str, Any] = {"radio": "radio0", "modes": ["g"], "channels": [1, 6], "advance": "manual"}


async def _phase(authed: httpx.AsyncClient, *phases: str, index: int | None = None) -> dict[str, Any]:
    for _ in range(400):
        job = (await authed.get(f"{W}/step-through")).json()
        if job and job["phase"] in phases and (index is None or job["index"] == index):
            return dict(job)
        await asyncio.sleep(0.01)
    raise AssertionError(f"never reached {phases}")


async def _start(authed: httpx.AsyncClient, body: dict[str, Any] = MANUAL) -> httpx.Response:
    preview = (await authed.post(f"{W}/step-through/preview", json=body)).json()
    return await authed.post(f"{W}/step-through/start", json={**body, "digest": preview["digest"]})


async def _parked(ctx: AppContext) -> bool:
    rec = ctx.routers.get("ap2")
    assert rec is not None
    status = json.loads((await (await ctx.pool.get(rec)).run("ubus call network.wireless status")).stdout)
    return status["radio0"]["up"] is False


async def test_step_routes(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    assert (await authed.get(f"{W}/step-through")).json() is None
    preview = (await authed.post(f"{W}/step-through/preview", json=MANUAL)).json()
    assert [s["channel"] for s in preview["steps"]] == [1, 6] and preview["restore_lines"]
    assert len(preview["step_lines"]) == 2 and preview["estimate_s"] == 40
    started = await authed.post(f"{W}/step-through/start", json={**MANUAL, "digest": preview["digest"]})
    assert started.status_code == 202, started.text
    await _phase(authed, "waiting for Next", index=1)
    assert (await authed.post(f"{W}/step-through/next")).status_code == 200
    await _phase(authed, "waiting for Next", index=2)
    assert (await authed.post(f"{W}/step-through/next")).status_code == 200
    job = await _phase(authed, "done", "stopped", "failed")
    assert job["phase"] == "done" and [r["proven"] for r in job["results"]] == [True, True]
    assert await _parked(ctx)
    bad = await authed.post(f"{W}/step-through/preview", json={**MANUAL, "channels": [14]})
    assert bad.status_code == 422 and "Channel 14" in bad.json()["detail"]


async def test_busy_matrix(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    assert (await _start(authed)).status_code == 202
    await _phase(authed, "waiting for Next")
    lines = len(ctx.audit.query())
    refused = {
        "wifi apply": await authed.post(
            f"{W}/apply",
            json={"radio": "radio0", "channels": {"kind": "set", "channels": [11]}, "digest": "x"},
        ),
        "options apply": await authed.post(
            f"{W}/options/apply", json={"radio": "radio0", "edits": [], "digest": "x"}
        ),
        "scan": await authed.post("/api/routers/ap2/rf/radio0/scan", json={"digest": "x"}),
        "reboot": await authed.post("/api/routers/ap2/system/reboot/start", json={"digest": "x"}),
        "reset": await authed.post(
            "/api/routers/ap2/system/reset/start", json={"digest": "x", "confirm_name": "x", "alone": True}
        ),
        "restore": await authed.post(
            "/api/routers/ap2/system/restore/start", json={"name": "x", "digest": "x"}
        ),
        "flash": await authed.post(
            "/api/routers/ap2/flash/start", json={"board": "b", "revision": "r", "sha256": "s", "digest": "x"}
        ),
    }
    for what, r in refused.items():
        assert r.status_code == 409, (what, r.text)
        assert "step-through runs on" in r.json()["detail"], (what, r.json())
    assert len(ctx.audit.query()) == lines  # nothing was sent
    await authed.post(f"{W}/step-through/stop")
    await _phase(authed, "done", "stopped", "failed")

    ctx.system._reboots["ap2"] = RebootJob(router_id="ap2", phase="waiting", started_at=datetime.now())
    r = await _start(authed)
    assert r.status_code == 409 and "is rebooting" in r.json()["detail"]


async def test_pending_restore_after_a_restart(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    rec = ctx.routers.get("ap2")
    assert rec is not None
    section = await ubus_call(
        await ctx.pool.get(rec), "uci", "get", {"config": "wireless", "section": "radio0"}
    )
    saved = saved_options((section or {})["values"])
    on_air = RadioRequest(radio="radio0", modes=ModeSelection.of("g"), channels=ChannelSelection.of(6))
    assert (await ctx.wifi.apply("ap2", on_air)).applied and not await _parked(ctx)
    folder = ctx.data.steps_dir  # what an app that ended in the middle of a step-through leaves
    record = {"router_id": "ap2", "radio": "radio0", "saved_at": "2026-11-12T09:00:00", "options": saved}
    (folder / "ap2-radio0.json").write_text(json.dumps(record), encoding="utf-8")
    pending = (await authed.get("/api/step-through/pending")).json()
    assert [(p["router_id"], p["radio"]) for p in pending] == [("ap2", "radio0")]
    blocked = await _start(authed)
    assert blocked.status_code == 409 and "first" in blocked.json()["detail"]
    r = await authed.post(f"{W}/step-through/restore", json={"radio": "radio0"})
    assert r.status_code == 200 and r.json()["verified"], r.text
    assert await _parked(ctx) and (await authed.get("/api/step-through/pending")).json() == []


async def test_shutdown_restores(ctx: AppContext) -> None:
    req = StepRequest("radio0", ("g",), (1, 6), advance="manual")
    plan = await ctx.steps.preview("ap2", req)
    await ctx.steps.start("ap2", req, plan.digest)
    for _ in range(400):
        job = ctx.steps.job("ap2")
        if job is not None and job.phase == "waiting for Next":
            break
        await asyncio.sleep(0.01)
    assert not await _parked(ctx)
    app = create_app(ctx)
    async with app.router.lifespan_context(app):
        pass  # the app quits in the middle of the step-through
    job = ctx.steps.job("ap2")
    assert job is not None and job.phase == "stopped" and not job.restore_pending
    assert not (ctx.data.steps_dir / "ap2-radio0.json").exists()
