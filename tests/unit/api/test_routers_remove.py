"""Remove from the app (#77 minor 10, the 1.x proposal's D4): refused with 409 while something of the app runs
on the router, naming it; removed as before when nothing does."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.probe.status import RouterStatus
from openwrtgui.wifi.step_service import PendingRestore


def _status(faults: int | None) -> RouterStatus:
    return RouterStatus(
        read_at=datetime(2026, 11, 17, 12, 0),
        uptime_s=60,
        load=(0.0, 0.0, 0.0),
        mem_total_kb=60000,
        mem_available_kb=30000,
        radios=(),
        interfaces=(),
        dhcp_server_on=None,
        faults_armed=faults,
    )


def _pending(ctx: AppContext) -> None:
    folder = ctx.steps._steps_dir  # noqa: SLF001 - a restore a step-through left, as the service saves it
    folder.mkdir(parents=True, exist_ok=True)
    saved = PendingRestore(router_id="ap2", radio="radio0", saved_at=datetime(2026, 11, 17), options={})
    (folder / "ap2-radio0.json").write_text(saved.model_dump_json(), encoding="utf-8")


async def _remove(authed: httpx.AsyncClient) -> httpx.Response:
    return await authed.delete("/api/routers/ap2")


async def test_armed_faults_refuse_the_remove(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.statuses["ap2"] = _status(2)
    r = await _remove(authed)
    assert r.status_code == 409
    assert r.json()["detail"] == "AP2 · office is not removed: 2 faults armed. Stop or clear them first."
    assert ctx.routers.get("ap2") is not None


async def test_a_pending_restore_refuses_the_remove(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    _pending(ctx)
    r = await _remove(authed)
    assert r.status_code == 409
    assert "a step-through restore waits on radio0" in r.json()["detail"]


async def test_a_running_flash_refuses_the_remove(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.flash, "running", lambda router_id: router_id == "ap2")
    r = await _remove(authed)
    assert r.status_code == 409
    assert "a flash runs" in r.json()["detail"]


async def test_a_running_step_through_refuses_the_remove(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.steps, "busy", lambda router_id: "A step-through runs on AP2 · office radio0")
    r = await _remove(authed)
    assert r.status_code == 409
    assert "a step-through runs on AP2 · office radio0" in r.json()["detail"]


async def test_a_running_capture_refuses_the_remove(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.captures, "running_on", lambda router_id: "a capture on br-lan runs")
    r = await _remove(authed)
    assert r.status_code == 409
    assert "a capture on br-lan runs" in r.json()["detail"]


async def test_two_at_once_are_both_named(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    ctx.statuses["ap2"] = _status(1)
    _pending(ctx)
    detail = (await _remove(authed)).json()["detail"]
    assert detail == (
        "AP2 · office is not removed: 1 fault armed; a step-through restore waits on radio0. "
        "Stop or clear them first."
    )


async def test_nothing_running_and_no_status_removes(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    """An unreachable router with no status is removable, as before."""
    ctx.statuses.pop("ap2", None)
    assert (await _remove(authed)).status_code == 200
    assert ctx.routers.get("ap2") is None


async def test_a_capture_service_says_what_runs(ctx: AppContext) -> None:
    assert ctx.captures.running_on("ap2") is None
