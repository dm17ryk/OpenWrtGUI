"""The simulated modem inside a simulated router: ifup/ifdown lte and what netifd then says."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.context import AppContext
from openwrtgui.lte import commands as c
from openwrtgui.transport.fake import ReplayTransport

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


async def test_ifdown_and_ifup_change_netifd_state(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap2"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport)
    up = json.loads((await t.run(c.iface_status("lte"))).stdout)
    lease = json.loads((await t.run(c.iface_status("lte_4"))).stdout)
    assert up["up"] is True and lease["ipv4-address"] == [{"address": "10.64.12.7", "mask": 30}]
    wwan = json.loads((await t.run(c.device_status("wwan0"))).stdout)
    assert wwan["statistics"]["rx_bytes"] > 0 and wwan["statistics"]["tx_bytes"] > 0
    assert (await t.run(c.IFDOWN_LTE)).exit_status == 0
    assert json.loads((await t.run(c.iface_status("lte"))).stdout)["up"] is False
    assert json.loads((await t.run(c.iface_status("lte_4"))).stdout)["up"] is False
    assert (await t.run(c.IFUP_LTE)).exit_status == 0
    assert json.loads((await t.run(c.iface_status("lte"))).stdout)["up"] is True


def test_every_bench_router_has_the_modem() -> None:
    routers = json.loads((FIXTURES / "sim" / "routers.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in routers if r.get("modem")] == ["ap1", "ap2", "ap3"]


async def test_ap1_answers_the_modem_reads(ctx: AppContext) -> None:
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert (await t.run(c.TTY_LIST)).exit_status == 0
