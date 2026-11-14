"""v1.0a2 D10a: the app's own apply drops the router's cached menu facts, so a page its change made LuCI
show is listed at once (v1.0a1 review: the facts cache was not dropped by the app's own uci writes)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from openwrtgui.context import AppContext
from openwrtgui.luci_bridge.depends import Facts
from openwrtgui.probe.luci_menu import LuciPage
from openwrtgui.store.routers import RouterRecord
from openwrtgui.system.leds import LedChange
from openwrtgui.transport.base import Transport


async def test_an_apply_by_the_app_reads_the_menu_facts_again(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(ctx.access, "_sleep", no_sleep)
    reads: list[str] = []
    original = ctx.luci._read_facts

    async def counted(rec: RouterRecord, t: Transport, pages: Sequence[LuciPage]) -> Facts:
        reads.append(rec.id)
        return await original(rec, t, pages)

    monkeypatch.setattr(ctx.luci, "_read_facts", counted)
    await ctx.luci.pages("ap2")
    await ctx.luci.pages("ap2")
    assert reads == ["ap2"]  # kept for a minute
    lan = next(r for r in (await ctx.access.leds("ap2")).rows if r.section == "led_lan")
    off = LedChange(rows=[lan.model_copy(update={"trigger": "none", "default": True, "port_mask": None})])
    result = await ctx.access.apply_leds("ap2", off, (await ctx.access.plan_leds("ap2", off)).digest)
    assert result.applied
    await ctx.luci.pages("ap2")
    assert reads == ["ap2", "ap2"]
