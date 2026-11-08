"""Upload and validate without flashing (the AP2 window's first half): the plan's checks, nothing left."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openwrtgui.context import AppContext
from openwrtgui.flash.plan import FlashRequest
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.simimage import SimImage

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "images"
MINI = (FIX / "mini-r35692.bin").read_bytes()
NEWER = (FIX / "mini-r35700.bin").read_bytes()
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
REQ = FlashRequest(
    board="dlink,dwr-921-c3-uboot", revision="r35700-0c0ffee000", sha256=hashlib.sha256(NEWER).hexdigest()
)
FW = f"/tmp/owg/fw-{REQ.sha256[:12]}.bin"


def _ready(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI, "mini-r35692.bin", NOW)
    ctx.profiles.import_image(NEWER, "mini-r35700.bin", NOW)


def _calls(ctx: AppContext) -> list[str]:
    """The audited commands in the order they ran (the log lists the newest first)."""
    return [e.command for e in reversed(ctx.audit.query())]


async def test_check_only_uploads_validates_and_takes_it_all_away(ctx: AppContext) -> None:
    _ready(ctx)
    plan = await ctx.flash.plan("ap2", REQ)
    check = await ctx.flash.check_only("ap2", REQ, plan.digest)
    assert check.ok, check
    assert check.detail == "AP2 · office accepted the image (validate_firmware_image, sysupgrade -T)"
    calls = _calls(ctx)
    assert any(c.startswith(f"cat > {FW}  # stdin:") for c in calls)
    assert f"sha256sum {FW}" in calls and f"sysupgrade -T {FW}" in calls
    assert calls[-2:] == [f"rm -f {FW}", "rmdir /tmp/owg 2>/dev/null || true"]
    assert not any("start-stop-daemon" in c or c.startswith("sysupgrade /tmp") for c in calls)
    assert ctx.flash.job("ap2") is None
    assert (await ctx.discovery.state("ap2")).revision == "r35692-b8bffeefdf"


async def test_check_only_reports_a_refusal_and_still_cleans_up(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(ctx)
    monkeypatch.setattr(SimImage, "_check", lambda self, data: (False, False))
    plan = await ctx.flash.plan("ap2", REQ)
    check = await ctx.flash.check_only("ap2", REQ, plan.digest)
    assert not check.ok
    assert check.detail == "AP2 · office refused the image: fwtool_device_match"
    assert _calls(ctx)[-2:] == [f"rm -f {FW}", "rmdir /tmp/owg 2>/dev/null || true"]


async def test_check_only_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    _ready(ctx_guard_live)
    plan = await ctx_guard_live.flash.plan("ap2", REQ)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.flash.check_only("ap2", REQ, plan.digest)
    assert not any(c.startswith("cat > ") for c in _calls(ctx_guard_live))
