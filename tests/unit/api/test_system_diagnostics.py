"""Diagnostics on the router (v0.6b D4): no preview, audited, bounded, refused during a harness run."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system import commands as s

PING = "timeout -s KILL 25 ping -c 4 -W 2 '192.168.1.10'"


def _commands(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def test_ping_returns_its_replies_and_is_audited(ctx: AppContext) -> None:
    result = await ctx.system.diagnose("ap2", "ping", "192.168.1.10")
    assert (result.tool, result.target, result.command, result.exit_status) == (
        "ping",
        "192.168.1.10",
        PING,
        0,
    )
    assert result.output.count("bytes from 192.168.1.10") == 4
    assert _commands(ctx)[-1] == PING


async def test_traceroute_and_nslookup(ctx: AppContext) -> None:
    trace = await ctx.system.diagnose("ap2", "traceroute", "8.8.8.8")
    assert trace.command == s.traceroute("8.8.8.8") and trace.output.startswith("traceroute to 8.8.8.8")
    lookup = await ctx.system.diagnose("ap2", "nslookup", "openwrt.org")
    assert lookup.exit_status == 0 and "Name:\topenwrt.org" in lookup.output


async def test_a_bad_address_is_a_result_not_an_error(ctx: AppContext) -> None:
    result = await ctx.system.diagnose("ap2", "ping", "nohost.invalid")
    assert result.exit_status == 1 and "bad address" in result.output


async def test_diagnostics_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    with pytest.raises(GuardLocked):
        await ctx_guard_live.system.diagnose("ap2", "ping", "192.168.1.10")
    assert not any("ping" in c for c in _commands(ctx_guard_live))


@pytest.mark.parametrize("target", ["-c 100 x", "a;b", "", "$(id)"])
async def test_unsafe_targets_are_refused(ctx: AppContext, target: str) -> None:
    with pytest.raises(ValueError):
        await ctx.system.diagnose("ap2", "ping", target)
    assert ctx.audit.query() == []


async def test_diagnose_endpoint(authed: httpx.AsyncClient) -> None:
    ok = await authed.post(
        "/api/routers/ap2/system/diagnose", json={"tool": "ping", "target": "192.168.1.10"}
    )
    assert ok.status_code == 200 and ok.json()["exit_status"] == 0
    bad = await authed.post("/api/routers/ap2/system/diagnose", json={"tool": "ping", "target": "a;b"})
    assert bad.status_code == 422
    wrong_tool = await authed.post("/api/routers/ap2/system/diagnose", json={"tool": "nmap", "target": "x"})
    assert wrong_tool.status_code == 422


async def test_diagnose_endpoint_during_a_run(authed_guard_live: httpx.AsyncClient) -> None:
    locked = await authed_guard_live.post(
        "/api/routers/ap2/system/diagnose", json={"tool": "ping", "target": "192.168.1.10"}
    )
    assert locked.status_code == 423
