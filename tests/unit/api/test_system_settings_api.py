"""System settings through the plain uci apply in the simulator: exact preview, apply, proof (v0.6b D5)."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system.settings import SystemSettings


async def test_hostname_previews_applies_and_is_proven_live(ctx: AppContext) -> None:
    plan = await ctx.system.plan_settings("ap2", SystemSettings(hostname="bench-ap2"))
    assert plan.lines == (
        "set -e",
        "uci set system.cfg01e48a.hostname='bench-ap2'",
        "uci commit system",
        "/etc/init.d/system reload",
    )
    assert not plan.rollback  # nothing here cuts the app off
    result = await ctx.system.apply_settings("ap2", SystemSettings(hostname="bench-ap2"), plan.digest)
    assert (result.applied, result.verified) == (True, True), result
    checks = {c.name: c for c in result.checks}
    assert checks["saved"].ok and checks["hostname"].ok and checks["hostname"].detail == "bench-ap2"
    assert (await ctx.system.overview("ap2")).hostname == "bench-ap2"


async def test_time_zone_is_proven_by_the_tz_file(ctx: AppContext) -> None:
    settings = SystemSettings(zonename="Asia/Jerusalem")
    plan = await ctx.system.plan_settings("ap2", settings)
    assert "uci set system.cfg01e48a.timezone='IST-2IDT,M3.4.4/26,M10.5.0'" in plan.lines
    result = await ctx.system.apply_settings("ap2", settings, plan.digest)
    checks = {c.name: c for c in result.checks}
    assert result.verified and checks["time zone"].detail == "IST-2IDT,M3.4.4/26,M10.5.0"
    assert (await ctx.system.settings("ap2")).zonename == "Asia/Jerusalem"


async def test_ntp_change_restarts_sysntpd(ctx: AppContext) -> None:
    settings = SystemSettings(ntp_servers=("pool.ntp.org",))
    plan = await ctx.system.plan_settings("ap2", settings)
    assert plan.lines[-1] == "/etc/init.d/sysntpd restart"
    result = await ctx.system.apply_settings("ap2", settings, plan.digest)
    assert result.verified and (await ctx.system.settings("ap2")).ntp_servers == ("pool.ntp.org",)


async def test_nothing_to_change(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="^Nothing to apply"):
        await ctx.system.plan_settings("ap2", SystemSettings(hostname="OpenWrt"))


async def test_settings_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    settings = SystemSettings(hostname="bench-ap2")
    plan = await ctx_guard_live.system.plan_settings("ap2", settings)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.apply_settings("ap2", settings, plan.digest)
    assert (await ctx_guard_live.system.settings("ap2")).hostname == "OpenWrt"


async def test_settings_endpoints(authed: httpx.AsyncClient) -> None:
    base = "/api/routers/ap2/system/settings"
    current = await authed.get(base)
    assert current.status_code == 200 and current.json()["hostname"] == "OpenWrt"
    assert current.json()["ntp_servers"][0] == "0.openwrt.pool.ntp.org"
    preview = await authed.post(f"{base}/preview", json={"hostname": "bench-ap2"})
    assert (
        preview.status_code == 200
        and preview.json()["lines"][1] == "uci set system.cfg01e48a.hostname='bench-ap2'"
    )
    applied = await authed.post(
        f"{base}/apply", json={"hostname": "bench-ap2", "digest": preview.json()["digest"]}
    )
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
    bad = await authed.post(f"{base}/preview", json={"zonename": "Mars/Base"})
    assert (bad.status_code, bad.json()["detail"]) == (422, "Mars/Base is not a time zone this router knows")
