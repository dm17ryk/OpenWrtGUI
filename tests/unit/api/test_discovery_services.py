"""Custom services (decision D10): state, start, stop and restart, proven by reading the state back."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.discovery.services import service_command
from openwrtgui.guard.bench_guard import GuardLocked

MINI = Path(__file__).resolve().parents[2] / "fixtures" / "images" / "mini-r35692.bin"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def import_mini(ctx: AppContext) -> None:
    ctx.profiles.import_image(MINI.read_bytes(), "mini-r35692.bin", NOW)


def test_service_command() -> None:
    assert service_command("wifi-mirror", "restart") == "/etc/init.d/wifi-mirror restart"
    with pytest.raises(ValueError, match=r"^wifi mirror is not a service name$"):
        service_command("wifi mirror", "stop")


async def test_services_listed_from_custom_and_overlay(ctx: AppContext) -> None:
    import_mini(ctx)
    s = await ctx.discovery.state("ap1")
    rows = {(r.name, r.source, r.package) for r in s.services}
    assert rows == {
        ("dwr921-internet-led", "custom", "dwr921-internet-led"),
        ("wifi-mirror", "overlay", None),
    }
    assert all(r.running is True and r.enabled is True for r in s.services)


async def test_stop_and_start_are_proven(ctx: AppContext) -> None:
    import_mini(ctx)
    plan = await ctx.discovery.plan_service("ap1", "wifi-mirror", "stop")
    assert plan.lines == ("/etc/init.d/wifi-mirror stop",)
    stopped = await ctx.discovery.apply_service("ap1", "wifi-mirror", "stop", plan.digest)
    assert (stopped.applied, stopped.verified) == (True, True)
    assert stopped.checks[0].name == "service wifi-mirror"
    assert (
        next(r for r in (await ctx.discovery.state("ap1")).services if r.name == "wifi-mirror").running
        is False
    )
    plan = await ctx.discovery.plan_service("ap1", "wifi-mirror", "start")
    started = await ctx.discovery.apply_service("ap1", "wifi-mirror", "start", plan.digest)
    assert started.verified


async def test_only_custom_services(ctx: AppContext) -> None:
    import_mini(ctx)
    with pytest.raises(
        ValueError, match=r"^dropbear is not a custom service; it is managed on System › Services$"
    ):
        await ctx.discovery.plan_service("ap1", "dropbear", "restart")


async def test_service_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    import_mini(ctx_guard_live)
    plan = await ctx_guard_live.discovery.plan_service("ap1", "wifi-mirror", "stop")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.discovery.apply_service("ap1", "wifi-mirror", "stop", plan.digest)


async def test_service_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    import_mini(ctx)
    body = {"name": "dwr921-internet-led", "action": "restart"}
    preview = await authed.post("/api/routers/ap1/discovery/service/preview", json=body)
    assert preview.json()["lines"] == ["/etc/init.d/dwr921-internet-led restart"]
    applied = await authed.post(
        "/api/routers/ap1/discovery/service/apply", json=body | {"digest": preview.json()["digest"]}
    )
    assert applied.json()["verified"] is True
