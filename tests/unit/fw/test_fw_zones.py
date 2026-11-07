"""Zones and forwardings: names, the own zone, zones in use."""

from __future__ import annotations

import pytest
from fwenv import FwEnv

from openwrtgui.fw.compile import ForwardingRequest, ZoneRequest

P = "uci -P /var/run/rpcd/uci-<session>"
LAN, WAN = "cfg02dc81", "cfg03dc81"


def _zone(section: str | None, name: str, networks: tuple[str, ...] = ()) -> ZoneRequest:
    return ZoneRequest(section, name, networks, "REJECT", "ACCEPT", "REJECT", False, False)


async def test_zone_rules(env: FwEnv) -> None:
    with pytest.raises(ValueError, match="^A zone name is 1 to 11 letters, digits or _$"):
        await env.fw.plan_zones("ap2", [_zone(None, "averyverylongzone")], [], None)
    with pytest.raises(ValueError, match="^A zone name is 1 to 11 letters, digits or _$"):
        await env.fw.plan_zones("ap2", [_zone(None, "guest\n")], [], None)
    with pytest.raises(ValueError, match="^There is already a zone named wan$"):
        await env.fw.plan_zones("ap2", [_zone(None, "wan")], [], None)
    with pytest.raises(
        ValueError, match="^lan carries this app's connection to AP2 · office; it cannot be deleted here.$"
    ):
        await env.fw.plan_zones("ap2", [], [LAN], None)
    with pytest.raises(ValueError, match="^lan carries this app's connection; it stays in zone lan.$"):
        await env.fw.plan_zones("ap2", [_zone(LAN, "lan", ())], [], None)
    with pytest.raises(
        ValueError, match="^Zone wan is used by 3 rules and 1 forwarding; delete or move them first.$"
    ):
        await env.fw.plan_zones("ap2", [], [WAN], None)
    with pytest.raises(ValueError, match="^There is no interface named guestnet$"):
        await env.fw.plan_zones("ap2", [_zone(None, "guest", ("guestnet",))], [], None)


async def test_add_zone_and_forwarding_plan(env: FwEnv) -> None:
    plan = await env.fw.plan_zones(
        "ap2",
        [_zone(None, "guest")],
        [],
        [ForwardingRequest("lan", "wan"), ForwardingRequest("guest", "wan")],
    )
    assert f"z1=$({P} add firewall zone)" in plan.lines
    assert f"{P} set firewall.$z1.name='guest'" in plan.lines
    assert f"{P} set firewall.$z1.input='REJECT'" in plan.lines
    assert f"f1=$({P} add firewall forwarding)" in plan.lines
    assert f"{P} set firewall.$f1.src='guest'" in plan.lines
    assert f"{P} set firewall.$f1.dest='wan'" in plan.lines
    assert not any("cfg04ad58" in line for line in plan.lines)  # lan→wan stays as it is


async def test_zone_rename_moves_its_forwardings_in_the_same_change(env: FwEnv) -> None:
    upserts = [_zone(None, "guest")]
    added = [ForwardingRequest("lan", "wan"), ForwardingRequest("guest", "wan")]
    plan = await env.fw.plan_zones("ap2", upserts, [], added)
    assert (await env.fw.apply_zones("ap2", upserts, [], added, plan.digest)).verified
    guest = next(z for z in (await env.fw.state("ap2")).conf.zones if z.name == "guest")
    renamed = [_zone(guest.section, "visitor")]
    with pytest.raises(ValueError, match="^Zone guest is used by 1 forwarding; delete or move them first.$"):
        await env.fw.plan_zones("ap2", renamed, [], None)
    moved = [ForwardingRequest("lan", "wan"), ForwardingRequest("visitor", "wan")]
    plan = await env.fw.plan_zones("ap2", renamed, [], moved)
    assert f"{P} set firewall.{guest.section}.name='visitor'" in plan.lines
    result = await env.fw.apply_zones("ap2", renamed, [], moved, plan.digest)
    assert result.verified, result
    conf = (await env.fw.state("ap2")).conf
    assert ("visitor", "wan") in [(f.src, f.dest) for f in conf.forwardings]
    assert "guest" not in [z.name for z in conf.zones]


async def test_add_zone_verified_in_sim(env: FwEnv) -> None:
    upserts, forwardings = [_zone(None, "guest")], [ForwardingRequest("lan", "wan")]
    plan = await env.fw.plan_zones("ap2", upserts, [], forwardings)
    result = await env.fw.apply_zones("ap2", upserts, [], forwardings, plan.digest)
    assert result.applied and result.verified, result
    assert "guest" in [z.name for z in (await env.fw.state("ap2")).conf.zones]
