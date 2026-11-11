"""System › Access › HTTP(S) (plan Task 11, D6) in the simulator: LuCI on or off the network (loopback
always kept), the HTTPS redirect (refused where nothing serves HTTPS, as on AP2)."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system import commands as s
from openwrtgui.system.access import HttpChange, parse_listeners


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(ctx.access, "_sleep", no_sleep)


async def _web(ctx: AppContext, router_id: str) -> set[str]:
    t = await ctx.pool.get(ctx.routers.get(router_id))  # type: ignore[arg-type]
    return {a for a, port in parse_listeners((await t.run(s.LISTENERS)).stdout) if port == 80}


async def test_luci_off_the_network_keeps_loopback(ctx: AppContext) -> None:
    off = HttpChange(luci_on_network=False)
    plan = await ctx.access.plan_http("ap2", off)
    assert plan.lines == (
        "set -e",
        "uci -q delete uhttpd.main.listen_http",
        "uci add_list uhttpd.main.listen_http='127.0.0.1:80'",
        "uci add_list uhttpd.main.listen_http='[::1]:80'",
        "uci -q delete uhttpd.main.listen_https",
        "uci add_list uhttpd.main.listen_https='127.0.0.1:443'",
        "uci add_list uhttpd.main.listen_https='[::1]:443'",
        "uci commit uhttpd",
        "/etc/init.d/uhttpd restart",
    )
    assert any("LuCI pages in this app keep working" in w for w in plan.warnings)
    result = await ctx.access.apply_http("ap2", off, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert await _web(ctx, "ap2") == {"127.0.0.1", "::1"}
    http = (await ctx.access.access("ap2")).http
    assert (http.luci_on_network, http.loopback_kept) == (False, True)
    on = HttpChange(luci_on_network=True)
    back = await ctx.access.apply_http("ap2", on, (await ctx.access.plan_http("ap2", on)).digest)
    assert (back.applied, back.verified) == (True, True)
    assert await _web(ctx, "ap2") == {"0.0.0.0", "::"}


async def test_redirect_https_applied(ctx: AppContext) -> None:
    change = HttpChange(redirect_https=True)
    plan = await ctx.access.plan_http("ap1", change)  # simulated ap1 serves HTTPS
    assert "uci set uhttpd.main.redirect_https='1'" in plan.lines
    assert any("LuCI pages in this app follow" in w for w in plan.warnings)
    result = await ctx.access.apply_http("ap1", change, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert (await ctx.access.access("ap1")).http.redirect_https is True


async def test_redirect_refused_without_https(ctx: AppContext) -> None:
    with pytest.raises(ValueError, match="serves no HTTPS"):
        await ctx.access.plan_http("ap2", HttpChange(redirect_https=True))


async def test_a_custom_listen_list_is_kept(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    script = (
        "set -e\nuci delete uhttpd.main.listen_http\nuci add_list uhttpd.main.listen_http='192.168.1.2:80'\n"
        "uci commit uhttpd"
    )
    assert (await t.run(script)).ok
    http = (await ctx.access.access("ap2")).http
    assert (http.luci_on_network, http.loopback_kept) == (None, False)
    with pytest.raises(ValueError, match="Nothing"):
        await ctx.access.plan_http("ap2", HttpChange(redirect_https=False))  # leaves the custom list alone


async def test_http_endpoints(authed: httpx.AsyncClient) -> None:
    preview = await authed.post("/api/routers/ap2/system/http/preview", json={"luci_on_network": False})
    assert preview.status_code == 200 and preview.json()["lines"][-1] == "/etc/init.d/uhttpd restart"


async def test_http_waits_for_the_run(ctx_guard_live: AppContext) -> None:
    change = HttpChange(luci_on_network=False)
    plan = await ctx_guard_live.access.plan_http("ap2", change)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.access.apply_http("ap2", change, plan.digest)
