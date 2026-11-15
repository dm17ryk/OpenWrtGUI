"""Legacy iptables (v1.0a2 D6) on ap4; AP2 has none."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.fw.iptables import RESET_NOTE
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.store.routers import RouterRecord


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


async def test_ap4_lists_its_tables(ctx: AppContext) -> None:
    add_ap4(ctx)
    state = await ctx.iptables.state("ap4")
    assert (state.iptables, state.ip6tables) == (True, True)
    assert [(t.program, t.table) for t in state.tables][:4] == [
        ("iptables", "filter"),
        ("iptables", "nat"),
        ("iptables", "mangle"),
        ("iptables", "raw"),
    ]
    assert state.tables[0].chains[0].name == "INPUT" and state.tables[0].error is None


async def test_ap2_has_no_iptables(ctx: AppContext) -> None:
    presence = await ctx.iptables.presence("ap2")
    assert (presence.iptables, presence.ip6tables) == (False, False)
    with pytest.raises(ValueError, match="no iptables"):
        await ctx.iptables.plan_reset("ap2")


async def test_counters_reset_and_proven(ctx: AppContext) -> None:
    add_ap4(ctx)
    plan = await ctx.iptables.plan_reset("ap4")
    assert plan.lines == ("iptables -Z", "ip6tables -Z") and plan.warnings == (RESET_NOTE,)
    result = await ctx.iptables.apply_reset("ap4", plan.digest)
    assert (result.applied, result.verified) == (True, True)


async def test_the_firewall_restarted(ctx: AppContext, authed: httpx.AsyncClient) -> None:
    add_ap4(ctx)
    preview = await authed.post("/api/routers/ap4/firewall/iptables/restart/preview")
    assert preview.json()["lines"] == ["/etc/init.d/firewall restart"]
    digest = preview.json()["digest"]
    done = await authed.post("/api/routers/ap4/firewall/iptables/restart/apply", json={"digest": digest})
    assert done.json()["verified"]


async def test_a_reset_refused_during_a_run(ctx_guard_live: AppContext) -> None:
    add_ap4(ctx_guard_live)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.iptables.apply_reset("ap4", None)
