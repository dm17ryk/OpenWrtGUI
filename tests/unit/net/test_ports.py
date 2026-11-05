"""Ports, VLANs, mirroring on the simulated swconfig switch (AP2's switch0: LAN1 = port 3 carries the PC)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest
from netenv import NetEnv

from openwrtgui.net.state import NetworkState, read_network
from openwrtgui.ports.compile import MirrorRequest, VlanRequest, enable_commands
from openwrtgui.ports.state import PortsState, read_ports
from openwrtgui.simnet import PC_MAC, SimNetwork

P = "uci -P /var/run/rpcd/uci-<session>"


def _sim(net: NetEnv, host: str = "192.168.1.2") -> SimNetwork:
    sim = net.connector.state(host).net
    assert sim is not None
    return sim


async def _vlan_sections(net: NetEnv) -> dict[int, str]:
    return {v.vlan: v.section for v in (await net.ports.state("ap2")).vlans}


async def test_ap2_front_panel(net: NetEnv) -> None:
    state = await net.ports.state("ap2")
    assert state.managed and state.switch == "switch0" and state.cpu_port == 6 and state.max_vlan == 15
    assert [(p.num, p.label) for p in state.ports] == [
        (3, "LAN1"),
        (2, "LAN2"),
        (1, "LAN3"),
        (0, "LAN4"),
        (4, "WAN"),
    ]
    lan1 = state.ports[0]
    assert lan1.own and lan1.lock == "carries this app's SSH" and lan1.link and lan1.speed_mbps == 100
    assert state.own_reason == "only-link" and state.can_disable
    wan = next(p for p in state.ports if p.label == "WAN")
    assert wan.enabled is True and not wan.own and wan.lock is None
    assert {v.vlan: v.used_by for v in state.vlans} == {1: ("lan",), 2: ("wan", "wan6")}
    assert state.mirror.available and state.mirror.monitor is None and state.mirror.sources == {}
    assert state.wifi_mirror.present is False


async def test_own_port_disable_refused(net: NetEnv) -> None:
    with pytest.raises(
        ValueError, match="LAN1 carries this app's SSH to AP2 · office; turning it off cuts the app off."
    ):
        await net.ports.plan_ports("ap2", 3, False)


async def test_candidates_locked_when_own_port_ambiguous(net: NetEnv) -> None:
    await net.ports.state("ap2")  # creates the simulated router
    _sim(net).extra_links.add(2)
    state = await net.ports.state("ap2")
    assert state.own_reason == "candidates"
    locked = {p.label: p.lock for p in state.ports if p.lock}
    assert locked == {"LAN1": "may carry this app's SSH", "LAN2": "may carry this app's SSH"}
    with pytest.raises(
        ValueError, match=r"LAN2 may carry this app's SSH to AP2 · office \(2 ports have a link"
    ):
        await net.ports.plan_ports("ap2", 2, False)
    await net.ports.apply_ports("ap2", 1, False)
    plan = await net.ports.plan_ports("ap2", None, None, all_on=True)
    assert plan.lines == ("swconfig dev switch0 port 1 set enable 1",)


async def _ports_with(net: NetEnv, change: Callable[[NetworkState], NetworkState]) -> PortsState:
    """The Ports state as read_ports makes it from a network state changed by `change`."""
    await net.ports.state("ap2")  # creates the simulated router and its description
    rec = net.rec("ap2")
    t = await net.pool.get(rec)
    desc = net.descriptions[rec.id]
    state, uci = await read_network(t, rec.id, desc)
    return await read_ports(t, rec, desc, change(state), uci)


async def test_own_path_not_placed_locks_every_linked_port(net: NetEnv) -> None:
    """Fail closed: when the app cannot tell how its SSH reaches the switch, no linked socket goes off."""
    state = await _ports_with(net, lambda s: replace(s, own_interface=None))
    assert state.own_reason == "unplaced"
    assert {p.label: p.lock for p in state.ports if p.lock} == {"LAN1": "may carry this app's SSH"}
    assert not any(p.own for p in state.ports)
    refusal = "LAN1 may carry this app's SSH to AP2 · office: the app cannot tell"
    with pytest.raises(ValueError, match=refusal):
        enable_commands(state, 3, False, "AP2 · office")
    assert enable_commands(state, 2, False, "AP2 · office") == ["swconfig dev switch0 port 2 set enable 0"]


async def test_legacy_ifname_list_places_the_own_vlan(net: NetEnv) -> None:
    def legacy(s: NetworkState) -> NetworkState:  # lan on `option ifname 'eth0.1 eth1'`, no bridge device
        lan = next(v for v in s.interfaces if v.conf is not None and v.conf.name == "lan")
        assert lan.conf is not None
        moved = replace(lan, conf=replace(lan.conf, device="eth0.1 eth1"))
        return replace(s, devices=(), interfaces=tuple(moved if v is lan else v for v in s.interfaces))

    state = await _ports_with(net, legacy)
    assert state.own_reason == "only-link"
    assert [p.label for p in state.ports if p.own] == ["LAN1"]


async def test_arl_wins(net: NetEnv) -> None:
    await net.ports.state("ap2")
    _sim(net).extra_links.add(2)
    _sim(net).arl[PC_MAC] = 2
    state = await net.ports.state("ap2")
    assert state.own_reason == "arl"
    assert [p.label for p in state.ports if p.own] == ["LAN2"] and [
        p.label for p in state.ports if p.lock
    ] == ["LAN2"]


async def test_disable_free_port_and_enable_all_in_sim(net: NetEnv) -> None:
    plan = await net.ports.plan_ports("ap2", 2, False)
    assert plan.lines == ("swconfig dev switch0 port 2 set enable 0",) and not plan.rollback
    off = await net.ports.apply_ports("ap2", 2, False, plan.digest)
    assert off.verified and [c.name for c in off.checks] == ["port LAN2"]
    assert next(p for p in (await net.ports.state("ap2")).ports if p.num == 2).enabled is False
    on = await net.ports.apply_ports("ap2", None, None, all_on=True)
    assert on.verified
    with pytest.raises(ValueError, match="Nothing to apply"):
        await net.ports.plan_ports("ap2", None, None, all_on=True)


async def test_vlan_rules(net: NetEnv) -> None:
    sections = await _vlan_sections(net)
    with pytest.raises(
        ValueError,
        match="Port LAN4 is untagged in VLAN 1 and VLAN 3; a port is untagged in one VLAN at most.",
    ):
        await net.ports.plan_vlans("ap2", [VlanRequest(None, 3, {0: "u", 6: "t"})], [])
    with pytest.raises(ValueError, match="VLAN numbers on this switch are 1 to 15"):
        await net.ports.plan_vlans("ap2", [VlanRequest(None, 16, {6: "t"})], [])
    with pytest.raises(ValueError, match="There is already a VLAN 2"):
        await net.ports.plan_vlans("ap2", [VlanRequest(None, 2, {6: "t"})], [])
    with pytest.raises(
        ValueError, match=r"VLAN 2 carries wan \(eth0\.2\)\. Move wan to another device first\."
    ):
        await net.ports.plan_vlans("ap2", [], [sections[2]])
    plan = await net.ports.plan_vlans("ap2", [VlanRequest(None, 4, {1: "t"})], [])
    assert "VLAN 4 has no CPU port: the router cannot reach it." in plan.warnings
    own = await net.ports.plan_vlans(
        "ap2", [VlanRequest(sections[1], 1, {1: "u", 2: "u", 3: "u", 6: "t"})], []
    )
    assert (
        "VLAN 1 carries lan, this app's connection; the change applies with a 60 s rollback." in own.warnings
    )


async def test_add_vlan_plan(net: NetEnv) -> None:
    plan = await net.ports.plan_vlans("ap2", [VlanRequest(None, 3, {1: "t", 6: "t"})], [])
    assert plan.rollback
    assert f"v1=$({P} add network switch_vlan)" in plan.lines
    assert f"{P} set network.$v1.ports='1t 6t'" in plan.lines


async def test_vlan_change_verified_in_sim(net: NetEnv) -> None:
    sections = await _vlan_sections(net)
    moved = {0: "u", 1: "u", 2: "u", 3: "u", 6: "t"}
    result = await net.ports.apply_vlans(
        "ap2", [VlanRequest(sections[1], 1, {k: v for k, v in moved.items() if k != 0})], []
    )
    assert result.verified and [c.name for c in result.checks] == ["reconnected", "confirmed", "switch"]
    vlan1 = next(v for v in (await net.ports.state("ap2")).vlans if v.vlan == 1)
    assert 0 not in vlan1.members


async def test_mirror_plan_and_apply(net: NetEnv) -> None:
    req = MirrorRequest(monitor=1, sources={2: (True, True)})
    plan = await net.ports.plan_mirror("ap2", req)
    switch = next(line for line in plan.lines if "mirror_monitor_port" in line)
    assert switch.endswith("mirror_monitor_port='1'")
    assert f"s1=$({P} add network switch_port)" in plan.lines
    assert (
        f"{P} set network.$s1.port='2'" in plan.lines
        and f"{P} set network.$s1.enable_mirror_rx='1'" in plan.lines
    )
    result = await net.ports.apply_mirror("ap2", req, plan.digest)
    assert result.verified, result
    mirror = (await net.ports.state("ap2")).mirror
    assert mirror.monitor == 1 and mirror.sources == {2: (True, True)}
    again = await net.ports.plan_mirror("ap2", MirrorRequest(monitor=1, sources={2: (True, False)}))
    assert not any("add network switch_port" in line for line in again.lines)  # the port's section is reused
    off = await net.ports.apply_mirror("ap2", MirrorRequest(monitor=None, sources={}))
    assert off.verified and (await net.ports.state("ap2")).mirror.sources == {}


async def test_mirror_monitor_cannot_be_source(net: NetEnv) -> None:
    with pytest.raises(ValueError, match="LAN3 is the monitor port; it cannot also be a source."):
        await net.ports.plan_mirror("ap2", MirrorRequest(monitor=1, sources={1: (True, False)}))


async def test_wifi_mirror_status(net: NetEnv) -> None:
    assert (await net.ports.state("ap1")).wifi_mirror.present
    assert (await net.ports.state("ap1")).wifi_mirror.running is True


async def test_dsa_router_not_managed(net: NetEnv) -> None:
    await net.ports.state("ap2")
    net.descriptions["ap2"] = replace(net.descriptions["ap2"], board=None)
    state = await net.ports.state("ap2")
    assert not state.managed and state.ports == ()
    with pytest.raises(ValueError, match="This router's switch is not managed by swconfig"):
        await net.ports.plan_ports("ap2", 2, False)
