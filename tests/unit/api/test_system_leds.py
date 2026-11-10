"""System › LEDs (plan Task 12, D9) in the simulator: led sections through the plain uci apply and
`/etc/init.d/led restart`, proven by each LED's active trigger."""

from __future__ import annotations

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.system.leds import LedChange, LedRow


@pytest.fixture(autouse=True)
def _fast(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(ctx.access, "_sleep", no_sleep)


async def _lan(ctx: AppContext) -> LedRow:
    return next(r for r in (await ctx.access.leds("ap2")).rows if r.section == "led_lan")


async def test_led_trigger_changed_and_proven(ctx: AppContext) -> None:
    lan = await _lan(ctx)
    off = LedChange(rows=[lan.model_copy(update={"trigger": "none", "default": True, "port_mask": None})])
    plan = await ctx.access.plan_leds("ap2", off)
    assert plan.lines == (
        "set -e",
        "uci set system.led_lan.trigger='none'",
        "uci set system.led_lan.default='1'",
        "uci -q delete system.led_lan.port_mask",
        "uci commit system",
        "/etc/init.d/led restart",
    )
    result = await ctx.access.apply_leds("ap2", off, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    assert [c.name for c in result.checks] == ["saved", "LED green:lan"]
    state = await ctx.access.leds("ap2")
    assert next(x for x in state.leds if x.sysfs == "green:lan").active == "none"
    back = LedChange(rows=[lan])
    undo = await ctx.access.apply_leds("ap2", back, (await ctx.access.plan_leds("ap2", back)).digest)
    assert (undo.applied, undo.verified) == (True, True)
    assert (await _lan(ctx)) == lan


async def test_led_added_and_removed(ctx: AppContext) -> None:
    lan = await _lan(ctx)
    wifi = LedRow(section=None, name="wifi", sysfs="green:wifi", trigger="timer", delayon=500, delayoff=250)
    add = LedChange(rows=[lan, wifi])
    plan = await ctx.access.plan_leds("ap2", add)
    assert any(line.endswith("add system led)") for line in plan.lines)
    result = await ctx.access.apply_leds("ap2", add, plan.digest)
    assert (result.applied, result.verified) == (True, True)
    rows = (await ctx.access.leds("ap2")).rows
    added = next(r for r in rows if r.sysfs == "green:wifi")
    assert (added.trigger, added.delayon, added.delayoff) == ("timer", 500, 250)
    drop = LedChange(rows=[lan])
    gone_plan = await ctx.access.plan_leds("ap2", drop)
    assert f"uci -q delete system.{added.section}" in gone_plan.lines
    gone = await ctx.access.apply_leds("ap2", drop, gone_plan.digest)
    assert gone.applied and [r.section for r in (await ctx.access.leds("ap2")).rows] == ["led_lan"]


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"sysfs": "blue:nope"}, "No LED blue:nope"),
        ({"trigger": "usbport"}, "has no trigger usbport"),
        ({"trigger": "timer", "port_mask": None, "delayon": 0, "delayoff": 100}, "1-10000"),
        ({"trigger": "netdev", "port_mask": None, "dev": "eth0", "mode": ("blink",)}, "netdev mode"),
        ({"trigger": "netdev", "port_mask": None, "dev": "nope0", "mode": ("link",)}, "No device nope0"),
        ({"port_mask": "ff"}, "mask"),
        ({"name": "a'b"}, "name"),
    ],
)
async def test_led_refusals(ctx: AppContext, update: dict[str, object], reason: str) -> None:
    lan = await _lan(ctx)
    with pytest.raises(ValueError, match=reason):
        await ctx.access.plan_leds("ap2", LedChange(rows=[lan.model_copy(update=update)]))


async def test_two_actions_on_one_led_refused(ctx: AppContext) -> None:
    lan = await _lan(ctx)
    twice = lan.model_copy(update={"section": None})
    with pytest.raises(ValueError, match="Two LED actions"):
        await ctx.access.plan_leds("ap2", LedChange(rows=[lan, twice]))


async def test_led_endpoints(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    lan = (await _lan(ctx)).model_copy(update={"trigger": "heartbeat", "port_mask": None, "inverted": True})
    body = {"rows": [lan.model_dump(mode="json")]}
    preview = await authed.post("/api/routers/ap2/system/leds/preview", json=body)
    assert preview.status_code == 200 and preview.json()["lines"][-1] == "/etc/init.d/led restart"


async def test_leds_wait_for_the_run(ctx_guard_live: AppContext) -> None:
    lan = next(r for r in (await ctx_guard_live.access.leds("ap2")).rows if r.section == "led_lan")
    change = LedChange(rows=[lan.model_copy(update={"trigger": "none", "port_mask": None})])
    plan = await ctx_guard_live.access.plan_leds("ap2", change)
    with pytest.raises(GuardLocked):
        await ctx_guard_live.access.apply_leds("ap2", change, plan.digest)
