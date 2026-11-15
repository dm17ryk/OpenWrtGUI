"""The VLAN editor's state (v1.0a3): the active bridge as LuCI picks it, its VLANs, the router's own ports
from board.json, their link from netifd, and the VLAN that carries the app's own interface (D3)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from openwrtgui.net import commands as c
from openwrtgui.net.state import NetworkState
from openwrtgui.ports.bridge import (
    BridgeDevice,
    BridgePortView,
    BridgeState,
    BridgeVlanConf,
    BridgeVlanView,
    bridge_devices,
    bridge_vlans,
    cell_of,
    find_active_bridge,
    members,
    natural,
    parse_spec,
    unsupported,
)
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import Transport

UNSUPPORTED = (
    "LuCI's Switch/VLAN page does not support this configuration either: fix it in LuCI's device dialog or "
    "the terminal."
)


def board_ports(desc: SelfDescription) -> frozenset[str]:
    """The router's own ports, as board.json wires them (`network.<role>.ports` and `.device`)."""
    board = desc.board
    out: set[str] = set()
    for role in (board.default_network if board else {}).values():
        if isinstance(role, dict):
            out |= {p for p in role.get("ports", []) if isinstance(p, str)}
            if isinstance(role.get("device"), str):
                out.add(role["device"])
    return frozenset(out)


async def _status(t: Transport) -> dict[str, Any]:
    r = await t.run(c.DEVICE_STATUS)
    try:
        value = json.loads(r.stdout) if r.ok and r.stdout.strip() else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _expanded(names: Sequence[str], net: NetworkState) -> list[str]:
    """Devices and, one hop down, the ports of the bridges among them (a legacy `ifname` lists several)."""
    bridges = {d.name: d for d in net.devices if d.type == "bridge"}
    return [*names, *(p for n in names if n in bridges for p in bridges[n].ports)]


def _used_by(vlan_device: str, net: NetworkState) -> tuple[str, ...]:
    return tuple(
        v.conf.name
        for v in net.interfaces
        if v.conf is not None and vlan_device in _expanded((v.conf.device or "").split(), net)
    )


def _own_vlan(bridge: str, net: NetworkState) -> tuple[int | None, str | None]:
    own = net.conf(net.own_interface) if net.own_interface else None
    if own is None or not own.device:
        return None, None
    names = _expanded(own.device.split(), net)
    if bridge in names:
        return None, (
            f"{own.name} uses {bridge} itself, so the app cannot tell which VLAN carries its connection: "
            "edit these VLANs in LuCI."
        )
    for name in names:
        head, _, vid = name.partition(".")
        if head == bridge and vid.isdigit():
            return int(vid), None
    return None, None


def _views(
    bridge: str, vlans: Sequence[BridgeVlanConf], net: NetworkState, own_vlan: int | None
) -> list[BridgeVlanView]:
    out = []
    for v in vlans:
        if v.device != bridge or v.vlan is None:
            continue
        parsed = [(text, parse_spec(text)) for text in v.entries]
        cells = {s.port: cell_of(s) for _, s in parsed if s}
        entries = {s.port: text for text, s in parsed if s}
        used = _used_by(f"{bridge}.{v.vlan}", net)
        out.append(BridgeVlanView(v.section, v.vlan, v.local, cells, entries, used, v.vlan == own_vlan))
    return sorted(out, key=lambda x: x.vlan)


def _absent(
    rec: RouterRecord,
    net: NetworkState,
    devices: Sequence[BridgeDevice],
    vlans: Sequence[BridgeVlanConf],
    physical: frozenset[str],
) -> BridgeState:
    filtering = [d for d in devices if d.vlan_filtering or any(v.device == d.name for v in vlans)]
    blocker = None
    if filtering and not physical:
        blocker = (
            f"{filtering[0].name} has members the app cannot tell from virtual devices (board.json lists no "
            "ports), so it shows no VLAN editor for it."
        )
    elif filtering:
        blocker = (
            f"{filtering[0].name} has members that are not ports of this router, so it shows no VLAN editor "
            "for it (LuCI shows none either)."
        )
    return BridgeState(rec.id, None, False, blocker, (), (), (), net.own_interface, None)


def _ports(
    names: Sequence[str], status: Mapping[str, Any], own: BridgeVlanView | None
) -> tuple[BridgePortView, ...]:
    out = []
    for name in names:
        entry = status.get(name)
        carrier = entry.get("carrier") if isinstance(entry, dict) else None
        link = carrier if isinstance(carrier, bool) else None
        out.append(BridgePortView(name, link, own is not None and name in own.members and link is not False))
    return tuple(out)


async def read_bridge(
    t: Transport, rec: RouterRecord, desc: SelfDescription, net: NetworkState, uci: Mapping[str, str]
) -> BridgeState:
    physical = board_ports(desc)
    devices, vlans = bridge_devices(uci), bridge_vlans(uci)
    active = find_active_bridge(devices, vlans, physical)
    if active is None:
        return _absent(rec, net, devices, vlans, physical)
    status = await _status(t)
    entry = status.get(active.name)
    live = entry.get("bridge-members", []) if isinstance(entry, dict) else []
    runtime = tuple(sorted((m for m in live if isinstance(m, str) and m not in physical), key=natural))
    issues = tuple(unsupported(active.name, vlans))
    own_vlan, placement = _own_vlan(active.name, net)
    views = _views(active.name, vlans, net, own_vlan)
    own = next((v for v in views if v.own), None)
    if own is None:
        own_vlan = None
    blocker = UNSUPPORTED if issues else placement
    return BridgeState(
        router_id=rec.id,
        bridge=active.name,
        editable=blocker is None,
        blocker=blocker,
        issues=issues,
        ports=_ports(members(active, vlans), status, own),
        vlans=tuple(views),
        own_interface=net.own_interface,
        own_vlan=own_vlan,
        runtime=runtime,
    )
