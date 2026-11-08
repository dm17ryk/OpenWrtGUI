"""Flash from an imported image in the simulator: upload, checks, sysupgrade by timer, come back."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwrtgui import simimage
from openwrtgui.context import AppContext
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.flash.service import FlashJob
from openwrtgui.simimage import SimImage
from openwrtgui.transport.base import CommandResult

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (FIX / "mini-r35692.bin").read_bytes()
NEWER = (FIX / "mini-r35700.bin").read_bytes()
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
BOARD = "dlink,dwr-921-c3-uboot"
REQ = FlashRequest(board=BOARD, revision="r35700-0c0ffee000", sha256=hashlib.sha256(NEWER).hexdigest())


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simimage, "REBOOT_S", 0.5)


def _ready(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI, "mini-r35692.bin", NOW)
    ctx.profiles.import_image(NEWER, "mini-r35700.bin", NOW)
    ctx.flash.every_s = 0.2


async def wait_job(ctx: AppContext, router_id: str, timeout: float = 20.0) -> FlashJob:
    for _ in range(int(timeout / 0.1)):
        job = ctx.flash.job(router_id)
        if job is not None and job.phase in ("done", "failed"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"flash still running: {ctx.flash.job(router_id)}")


async def _flash(ctx: AppContext, router_id: str = "ap2") -> FlashJob:
    plan = await ctx.flash.plan(router_id, REQ)
    await ctx.flash.start(router_id, REQ, plan.digest)
    return await wait_job(ctx, router_id)


def _calls(ctx: AppContext) -> list[str]:
    return [e.command for e in ctx.audit.query()]


async def test_flash_keep_settings_in_sim(ctx: AppContext) -> None:
    _ready(ctx)
    job = await _flash(ctx)
    assert job.phase == "done", job
    assert job.detail is not None
    assert job.detail.startswith("Flashed AP2 · office with r35700-0c0ffee000 in 0 min ")
    assert job.sent == job.total == len(NEWER)
    assert ctx.discovery.checklists.latest("ap2") is not None  # saved before the flash
    assert any("sysupgrade /tmp/owg/fw-" in c for c in _calls(ctx))
    assert any(c.startswith(f"cat > /tmp/owg/fw-{REQ.sha256[:12]}.bin  # stdin:") for c in _calls(ctx))
    state = await ctx.discovery.state("ap2")
    assert state.revision == "r35700-0c0ffee000"


async def test_failed_upload_removes_the_partial_file(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(ctx)
    monkeypatch.setattr(
        SimImage, "upload", lambda self, command, data: CommandResult(command, "", "No space left", 1)
    )
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error is not None and "No space left" in job.error
    calls = _calls(ctx)
    assert f"rm -f /tmp/owg/fw-{REQ.sha256[:12]}.bin" in calls
    assert not any("start-stop-daemon" in c for c in calls)


async def test_validate_refusal_flashes_nothing(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(ctx)
    monkeypatch.setattr(SimImage, "_check", lambda self, data: (False, False))
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error == "AP2 · office refused the image: fwtool_device_match"
    assert not any("start-stop-daemon" in c for c in _calls(ctx))


async def test_run_starting_during_upload_stops_before_sysupgrade(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(ctx)
    original = SimImage.upload

    def upload_then_run_starts(self: SimImage, command: str, data: bytes) -> CommandResult | None:
        monkeypatch.setenv("OPENWRTGUI_SIM_GUARD", "live")
        ctx.guard.check_local()
        return original(self, command, data)

    monkeypatch.setattr(SimImage, "upload", upload_then_run_starts)
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error is not None and "dima_night" in job.error
    calls = _calls(ctx)
    assert f"rm -f /tmp/owg/fw-{REQ.sha256[:12]}.bin" in calls
    assert not any("start-stop-daemon" in c for c in calls)


async def test_old_revision_after_reboot_is_not_success(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(ctx)
    finish = SimImage._finish_flash

    def stage2_refused(self: SimImage) -> None:
        finish(self)
        self._load(MINI)  # rebooted into the old firmware

    monkeypatch.setattr(SimImage, "_finish_flash", stage2_refused)
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error == "AP2 · office came back on r35692-b8bffeefdf, not r35700-0c0ffee000"


async def test_other_board_at_the_address_is_not_success(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(ctx)
    monkeypatch.setattr(
        SimImage,
        "_board_answer",
        lambda self: json.dumps({"board_name": "other,board", "release": {"revision": self.revision}}),
    )
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error == "AP2 · office answers as other,board, not dlink,dwr-921-c3-uboot"


async def test_no_answer_in_ten_minutes(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(ctx)
    monkeypatch.setattr(simimage, "REBOOT_S", 1e9)
    ctx.flash.come_back_s = 3.0
    job = await _flash(ctx)
    assert job.phase == "failed"
    assert job.error is not None
    assert job.error.startswith("AP2 · office did not come back within 3 s. It may still be writing flash")


async def test_flash_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    _ready(ctx)
    body = REQ.model_dump()
    preview = await authed.post("/api/routers/ap2/flash/preview", json=body)
    assert preview.status_code == 200
    assert preview.json()["lines"][0] == "mkdir -p /tmp/owg"
    stale = await authed.post("/api/routers/ap2/flash/start", json=body | {"digest": "0" * 16})
    assert stale.status_code == 409
    started = await authed.post(
        "/api/routers/ap2/flash/start", json=body | {"digest": preview.json()["digest"]}
    )
    assert (started.status_code, started.json()["phase"]) == (200, "upload")
    again = await authed.post(
        "/api/routers/ap2/flash/start", json=body | {"digest": preview.json()["digest"]}
    )
    assert again.status_code == 409
    job = await wait_job(ctx, "ap2")
    assert job.phase == "done"
    assert (await authed.get("/api/routers/ap2/flash")).json()["phase"] == "done"
