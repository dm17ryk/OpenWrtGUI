"""System › Plugins (v1.0a2 D4) on ap4, the simulated later image: read, switch, remove, refused during a
run."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.store.routers import RouterRecord
from openwrtgui.system.plugins import LOGIN_WARNING, PluginChange

CSP_ID = "c0ffee2cf63e160c091224d95d69cdff"
GONE_ID = "0123456789abcdef0123456789abcdef"


def add_ap4(c: AppContext) -> None:
    c.routers.upsert(
        RouterRecord(
            id="ap4",
            name="AP4 · later image",
            host="192.168.1.6",
            auth="key",
            added_at=datetime(2026, 11, 14, 9, 0),
        )
    )


async def test_the_plugins_tab_reads_ap4(ctx: AppContext) -> None:
    add_ap4(ctx)
    state = await ctx.plugins.state("ap4")
    assert state.enabled and [g.key for g in state.groups] == ["auth_login", "http_headers"]
    by = {p.id: p for p in state.plugins}
    assert (by[CSP_ID].title, by[CSP_ID].enabled) == ("Content Security Policy", True)
    assert not by[GONE_ID].installed


async def test_a_router_without_plugins_shows_the_switches(ctx: AppContext) -> None:
    state = await ctx.plugins.state("ap2")
    assert (state.enabled, state.groups, state.plugins, state.missing) == (False, [], [], ())


async def test_a_plugin_switched_off_and_on(ctx: AppContext) -> None:
    add_ap4(ctx)
    off = PluginChange(plugins={CSP_ID: False})
    plan = await ctx.plugins.plan("ap4", off)
    assert plan.lines == ("set -e", f"uci -q delete luci_plugins.{CSP_ID}.enabled", "uci commit luci_plugins")
    result = await ctx.plugins.apply("ap4", off, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert not {p.id: p for p in (await ctx.plugins.state("ap4")).plugins}[CSP_ID].enabled
    on = PluginChange(plugins={CSP_ID: True})
    assert (await ctx.plugins.apply("ap4", on, (await ctx.plugins.plan("ap4", on)).digest)).verified


async def test_a_gone_plugin_removed(ctx: AppContext) -> None:
    add_ap4(ctx)
    gone = PluginChange(remove=[GONE_ID])
    result = await ctx.plugins.apply("ap4", gone, (await ctx.plugins.plan("ap4", gone)).digest)
    assert result.verified
    assert GONE_ID not in {p.id for p in (await ctx.plugins.state("ap4")).plugins}


async def test_turning_on_login_plugins_warns(ctx: AppContext) -> None:
    add_ap4(ctx)
    plan = await ctx.plugins.plan("ap4", PluginChange(groups={"auth_login": True}))
    assert plan.warnings == (LOGIN_WARNING,)


async def test_the_api_previews_and_applies(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    add_ap4(ctx)
    preview = await authed.post("/api/routers/ap4/system/plugins/preview", json={"enabled": False})
    assert preview.status_code == 200
    assert "uci -q delete luci_plugins.global.enabled" in preview.json()["lines"]
    done = await authed.post(
        "/api/routers/ap4/system/plugins/apply", json={"enabled": False, "digest": preview.json()["digest"]}
    )
    assert done.status_code == 200 and done.json()["verified"]
    assert (await authed.get("/api/routers/ap4/system/plugins")).json()["enabled"] is False


async def test_a_plugin_change_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    add_ap4(ctx_guard_live)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.plugins.apply("ap4", PluginChange(enabled=False), None)
