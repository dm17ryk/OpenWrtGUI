"""The VLAN editor's state read from the router (v1.0a3 D2, D3): ap5, and AP2 with no bridge VLANs (D7)."""

from __future__ import annotations

from dataclasses import replace

from bridgeenv import BridgeEnv

from openwrtgui.net.parse import devices, interfaces
from openwrtgui.net.state import InterfaceView, read_network
from openwrtgui.ports.bridge import BridgeState
from openwrtgui.ports.bridge_state import board_ports, read_bridge


async def _with(bridge: BridgeEnv, change: dict[str, str], drop: tuple[str, ...] = ()) -> BridgeState:
    """ap5's state as read_bridge makes it from ap5's network read with `change` applied to the uci (and the
    keys under `drop` removed). The sim's own config stays as it is, so the app still reaches it."""
    await bridge.state("ap5")
    rec = bridge.routers.get("ap5")
    assert rec is not None
    t = await bridge.pool.get(rec)
    desc = bridge.descriptions["ap5"]
    net, uci = await read_network(t, rec.id, desc)
    kept = {k: v for k, v in uci.items() if not (drop and k.startswith(drop))}
    changed = kept | change
    views = tuple(InterfaceView(i, None, i.name == net.own_interface, None) for i in interfaces(changed))
    moved = replace(net, interfaces=views, devices=tuple(devices(changed)))
    return await read_bridge(t, rec, desc, moved, changed)


async def test_ap5_state(bridge: BridgeEnv) -> None:
    state = await bridge.state("ap5")
    assert (state.bridge, state.editable, state.blocker, state.issues) == ("switch", True, None, ())
    assert [(p.name, p.link, p.may_carry) for p in state.ports] == [
        ("lan1", False, False),
        ("lan2", False, False),
        ("lan3", True, True),
        ("lan4", False, False),
    ]
    assert [(v.vlan, v.local, v.members, v.used_by, v.own) for v in state.vlans] == [
        (1, True, {"lan1": "u", "lan2": "u", "lan3": "u", "lan4": "u"}, ("lan",), True),
        (10, True, {"lan1": "t", "lan4": "t"}, ("iot",), False),
    ]
    assert (state.own_interface, state.own_vlan, state.runtime) == ("lan", 1, ())
    assert board_ports(bridge.descriptions["ap5"]) == frozenset({"lan1", "lan2", "lan3", "lan4", "wan"})


async def test_ap2_has_no_bridge_vlans(bridge: BridgeEnv) -> None:
    """D7: AP2 is swconfig; the read finds no bridge."""
    state = await bridge.state("ap2")
    assert (state.bridge, state.editable, state.blocker, state.vlans) == (None, False, None, ())


async def test_a_second_linked_port_may_carry_too(bridge: BridgeEnv) -> None:
    await bridge.state("ap5")
    bridge.sim().dsa_links.add("lan1")
    state = await bridge.state("ap5")
    assert [p.name for p in state.ports if p.may_carry] == ["lan1", "lan3"]


async def test_the_own_vlan_wherever_lan_sits(bridge: BridgeEnv) -> None:
    """Review Focus 4: on switch.1, on a bridge over switch.1, on the bridge itself, or on wan."""
    over = {
        "network.lan.device": "br-lan",
        "network.d9": "device",
        "network.d9.name": "br-lan",
        "network.d9.type": "bridge",
        "network.d9.ports": "switch.1",
    }
    through = await _with(bridge, over)
    assert (through.own_vlan, through.editable) == (1, True)
    assert next(v for v in through.vlans if v.vlan == 1).used_by == ("lan",)
    itself = await _with(bridge, {"network.lan.device": "switch"})
    assert itself.own_vlan is None and not itself.editable
    assert itself.blocker == (
        "lan uses switch itself, so the app cannot tell which VLAN carries its connection: "
        "edit these VLANs in LuCI."
    )
    on_wan = await _with(bridge, {"network.lan.device": "wan"})
    assert (on_wan.own_vlan, on_wan.editable) == (None, True)
    assert not any(p.may_carry for p in on_wan.ports)


async def test_an_own_vlan_without_a_section_stays_the_own_vlan(bridge: BridgeEnv) -> None:
    """Final review Important 2a: lan on switch.1 with no bridge-vlan for VLAN 1 (the bridge filters because
    of VLAN 10): VLAN 1 is still the app's own, so a section for it is refused in the rules."""
    state = await _with(bridge, {}, drop=("network.cfg040f15",))
    assert [v.vlan for v in state.vlans] == [10]
    assert (state.own_vlan, state.editable) == (1, True)


async def test_an_8021q_device_or_an_alias_places_the_own_vlan(bridge: BridgeEnv) -> None:
    """Final review Important 2b: lan on a VLAN device section (`type 8021q`, `ifname switch`, `vid 1`), or on
    an alias (`@base`) of an interface on switch.1."""
    vlan_device = {
        "network.lan.device": "vlan1",
        "network.d8": "device",
        "network.d8.type": "8021q",
        "network.d8.ifname": "switch",
        "network.d8.vid": "1",
        "network.d8.name": "vlan1",
    }
    state = await _with(bridge, vlan_device)
    assert (state.own_vlan, state.editable) == (1, True)
    assert next(v for v in state.vlans if v.vlan == 1).used_by == ("lan",)
    assert [p.name for p in state.ports if p.may_carry] == ["lan3"]
    alias = {
        "network.lan.device": "@base",
        "network.base": "interface",
        "network.base.device": "switch.1",
        "network.base.proto": "none",
    }
    aliased = await _with(bridge, alias)
    assert (aliased.own_vlan, aliased.editable) == (1, True)
    assert "lan" in next(v for v in aliased.vlans if v.vlan == 1).used_by


async def test_a_bridge_port_used_directly_makes_the_card_read_only(bridge: BridgeEnv) -> None:
    """Final review Important 2: when the own interface's device is one of the bridge's ports, the app
    cannot tell how a VLAN change reaches its connection, so it fails closed."""
    state = await _with(bridge, {"network.lan.device": "lan3"})
    assert not state.editable and state.own_vlan is None
    assert state.blocker == (
        "lan uses lan3, a port of switch, so the app cannot tell how VLAN changes reach its connection: "
        "edit these VLANs in LuCI."
    )


async def test_luci_unsupported_config_keeps_the_card_read_only(bridge: BridgeEnv) -> None:
    state = await _with(bridge, {"network.cfg050f15.ports": "lan1:t* lan4:t"})
    assert not state.editable
    assert state.issues == ("VLAN 10: lan1 is tagged and PVID at once (lan1:t*)",)
    assert state.blocker == (
        "LuCI's Switch/VLAN page does not support this configuration either: fix it in LuCI's device dialog "
        "or the terminal."
    )


async def test_wifi_at_run_time_is_listed_not_edited(bridge: BridgeEnv) -> None:
    """Review Focus 3, D2 d: a live member that is not an own port does not hide the bridge."""
    await bridge.state("ap5")
    bridge.sim().dsa_wifi.append("phy0-ap0")
    state = await bridge.state("ap5")
    assert state.bridge == "switch" and state.editable and state.runtime == ("phy0-ap0",)
    assert all(p.name != "phy0-ap0" for p in state.ports)


async def test_no_board_ports_no_editor(bridge: BridgeEnv) -> None:
    await bridge.state("ap5")
    desc = bridge.descriptions["ap5"]
    assert desc.board is not None
    bridge.descriptions["ap5"] = replace(desc, board=replace(desc.board, default_network={}))
    state = await bridge.state("ap5")
    assert state.bridge is None and state.blocker == (
        "switch has members the app cannot tell from virtual devices (board.json lists no ports), so it "
        "shows no VLAN editor for it."
    )
