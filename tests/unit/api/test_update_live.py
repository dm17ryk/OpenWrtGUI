"""The update asks before it stops a step-through, a capture or frame analysis (spec 9.3, v0.7 plan D15)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.app import create_app
from openwrtgui.capture.service import CaptureRequest
from openwrtgui.context import AppContext
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.wifi.steps import StepRequest

INSTALL = "/api/update/install"


async def _installed(version: str) -> list[str]:
    return ["installer.exe", "/VERYSILENT"]


async def _step_through(ctx: AppContext) -> None:
    req = StepRequest("radio0", ("g",), (1, 6), advance="manual")
    await ctx.steps.start("ap2", req, (await ctx.steps.preview("ap2", req)).digest)
    for _ in range(400):
        job = ctx.steps.job("ap2")
        if job is not None and job.phase == "waiting for Next":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the step-through did not start")


async def test_install_asks_first_for_live_operations(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.updater, "install", _installed)
    await _step_through(ctx)
    r = await authed.post(INSTALL, json={"version": "0.7.0"})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["live"] == ["Step-through on AP2 · office radio0"] and body["open_terminals"] == 0
    assert body["detail"] == "Live work is running"
    assert not ctx.quit_event.is_set() and ctx.steps.running("ap2")


async def test_install_force_stops_them_and_restores(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.updater, "install", _installed)
    await _step_through(ctx)
    r = await authed.post(INSTALL, json={"version": "0.7.0", "force": True})
    assert r.status_code == 202, r.text
    job = ctx.steps.job("ap2")
    assert job is not None and job.phase == "stopped" and not job.restore_pending  # restored first
    assert ctx.quit_event.is_set() and ctx.exit_command == ["installer.exe", "/VERYSILENT"]


REINSTALL = "/api/update/reinstall-previous"


async def test_reinstall_previous_asks_first_for_live_operations(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #59 review: going back to the previous version stops live work the same way an update does."""
    monkeypatch.setattr(ctx.updater, "reinstall_command", lambda: ["previous.exe", "/VERYSILENT"])
    await _step_through(ctx)
    r = await authed.post(REINSTALL)
    assert r.status_code == 409, r.text
    assert r.json()["live"] == ["Step-through on AP2 · office radio0"]
    assert not ctx.quit_event.is_set() and ctx.steps.running("ap2")
    forced = await authed.post(REINSTALL, json={"force": True})
    assert forced.status_code == 202, forced.text
    job = ctx.steps.job("ap2")
    assert job is not None and job.phase == "stopped" and not job.restore_pending  # restored first
    assert ctx.quit_event.is_set() and ctx.exit_command == ["previous.exe", "/VERYSILENT"]


class _HeldStream:
    """A capture that runs until it is closed."""

    exit_status: int | None = None
    stderr = ""

    def __init__(self) -> None:
        self.ended = asyncio.Event()

    async def read(self, n: int) -> bytes:
        await self.ended.wait()
        return b""

    async def close(self) -> None:
        self.ended.set()


async def test_shutdown_stops_a_mon0_capture(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR #59 review: the app closing ends a capture (its file closed) and removes owgmon0 first."""

    async def stream(self: ReplayTransport, command: str) -> _HeldStream:
        return _HeldStream()

    monkeypatch.setattr(ReplayTransport, "stream", stream)
    view = await ctx.captures.start("ap1", CaptureRequest("mon0", "", 600))
    app = create_app(ctx)
    async with app.router.lifespan_context(app):
        pass  # the app quits in the middle of the capture
    done = next(v for v in ctx.captures.list_all() if v.id == view.id)
    assert not done.running
    commands = [e.command for e in ctx.audit.query()]
    assert "iw dev owgmon0 del" in commands


async def test_install_with_nothing_live_goes_ahead(
    authed: httpx.AsyncClient, ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ctx.updater, "install", _installed)
    r = await authed.post(INSTALL, json={"version": "0.7.0"})
    assert r.status_code == 202 and ctx.quit_event.is_set()
