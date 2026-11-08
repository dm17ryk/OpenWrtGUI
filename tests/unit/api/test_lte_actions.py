"""Connect, disconnect and the safe modem reboot (low_power, online) in the simulator."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.lte.service import LteBusy
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.wifi.service import PreviewChanged

DEV = "/dev/cdc-wdm0"
LOW = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode low_power"
ONLINE = f"uqmi -s -d {DEV} -t 3000 --set-device-operating-mode online"
READ = f"uqmi -s -d {DEV} -t 2000 --get-device-operating-mode"


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext) -> None:
    ctx.lte.poll_s = 0.0
    ctx.lte.readback_s = 0.0


def _calls(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def _modem(ctx: AppContext):  # type: ignore[no-untyped-def]
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


async def test_disconnect_then_connect(ctx: AppContext) -> None:
    plan = await ctx.lte.plan_action("ap2", "disconnect")
    assert plan.lines == ("ifdown lte",)
    assert plan.warnings == (
        "AP2 · office's LTE session drops; devices that route through it lose the internet until it is back",
    )
    down = await ctx.lte.apply_action("ap2", "disconnect", plan.digest)
    assert (down.applied, down.verified) == (True, True)
    assert not (await _modem(ctx)).connected
    plan = await ctx.lte.plan_action("ap2", "connect")
    up = await ctx.lte.apply_action("ap2", "connect", plan.digest)
    assert (up.applied, up.verified) == (True, True)
    checks = {c.name: c for c in up.checks}
    assert (
        checks["lte up"].ok and checks["lte_4 address"].ok and checks["lte_4 address"].detail == "10.64.12.7"
    )
    assert _calls(ctx)[-2:] == ["ifdown lte", "ifup lte"]


async def test_connect_without_an_address_yet_is_not_a_failure(ctx: AppContext) -> None:
    modem = await _modem(ctx)
    modem.lease = False
    plan = await ctx.lte.plan_action("ap2", "connect")
    result = await ctx.lte.apply_action("ap2", "connect", plan.digest)
    address = next(c for c in result.checks if c.name == "lte_4 address")
    assert result.verified and address.ok is None
    assert address.detail == "no address yet: waiting for the carrier's DHCP"


async def test_reboot_goes_low_power_then_online_then_ifup(ctx: AppContext) -> None:
    plan = await ctx.lte.plan_action("ap2", "reboot")
    assert plan.lines == (LOW, READ, ONLINE, READ, "ifup lte")
    result = await ctx.lte.apply_action("ap2", "reboot", plan.digest)
    assert result.verified, result.checks
    calls = _calls(ctx)
    assert calls.index(LOW) < calls.index(ONLINE) < calls.index("ifup lte")
    assert {c.name for c in result.checks} >= {"modem low_power", "modem online", "lte up"}


async def test_a_modem_that_stays_low_power_stops_before_ifup(ctx: AppContext) -> None:
    (await _modem(ctx)).stays_low_power = True
    plan = await ctx.lte.plan_action("ap2", "reboot")
    result = await ctx.lte.apply_action("ap2", "reboot", plan.digest)
    assert (result.applied, result.verified) == (True, False)
    assert result.error == "The modem did not go online; it may need ifup lte or a power cycle"
    assert "ifup lte" not in _calls(ctx)


async def test_actions_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    ctx_guard_live.lte.poll_s = ctx_guard_live.lte.readback_s = 0.0
    plan = await ctx_guard_live.lte.plan_action("ap2", "disconnect")
    with pytest.raises(GuardLocked):
        await ctx_guard_live.lte.apply_action("ap2", "disconnect", plan.digest)
    assert "ifdown lte" not in [e.command for e in ctx_guard_live.audit.query()]


async def test_one_lte_action_at_a_time(ctx: AppContext) -> None:
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    (await _modem(ctx)).stays_low_power = True  # the online read-back waits in sleep
    ctx.lte.readback_s = 1.0
    ctx.lte._sleep = slow  # type: ignore[assignment]
    plan = await ctx.lte.plan_action("ap2", "reboot")
    first = asyncio.create_task(ctx.lte.apply_action("ap2", "reboot", plan.digest))
    await asyncio.sleep(0.05)
    connect = await ctx.lte.plan_action("ap2", "connect")
    with pytest.raises(LteBusy, match=r"^An LTE action is already running on AP2 · office$"):
        await ctx.lte.apply_action("ap2", "connect", connect.digest)
    gate.set()
    await first


async def test_stale_digest(ctx: AppContext) -> None:
    with pytest.raises(PreviewChanged):
        await ctx.lte.apply_action("ap2", "connect", "0000000000000000")


async def test_action_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    preview = await authed.post("/api/routers/ap2/lte/action/preview", json={"action": "disconnect"})
    assert preview.status_code == 200 and preview.json()["lines"] == ["ifdown lte"]
    applied = await authed.post(
        "/api/routers/ap2/lte/action/apply", json={"action": "disconnect", "digest": preview.json()["digest"]}
    )
    assert (applied.status_code, applied.json()["verified"]) == (200, True)
    bad = await authed.post("/api/routers/ap2/lte/action/preview", json={"action": "reset"})
    assert bad.status_code == 422
