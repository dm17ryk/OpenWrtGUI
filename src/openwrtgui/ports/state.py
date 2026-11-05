"""What the Ports screen shows: the front panel, the app's own port, VLANs, the mirror, Wi-Fi mirror status.

The app's own port (the one its SSH comes in on): the switch's ARL table entry of the PC's MAC when the
switch has one; otherwise the external ports with a link in the VLAN that carries the app's interface. One
such port is the own port; several are all locked, since any of them may carry the SSH (plan v0.3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.net import commands as c
from openwrtgui.net.state import NetworkState
from openwrtgui.ports.parse import (
    parse_arl,
    parse_arp,
    parse_swconfig_help,
    parse_swconfig_show,
    switch_conf,
    switch_vlans,
)
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import Transport

Cell = Literal["u", "t"]
OwnReason = Literal["arl", "only-link", "candidates", "none"]
OWN = "carries this app's SSH"
MAYBE_OWN = "may carry this app's SSH"


@dataclass(frozen=True)
class PortView:
    num: int
    label: str
    role: str | None
    link: bool
    speed_mbps: int | None
    full_duplex: bool | None
    enabled: bool | None  # None: the switch cannot turn this port on or off
    own: bool
    lock: str | None


@dataclass(frozen=True)
class VlanView:
    section: str
    vlan: int
    vid: int | None
    members: dict[int, Cell]
    device: str | None
    used_by: tuple[str, ...]


@dataclass(frozen=True)
class MirrorView:
    available: bool
    monitor: int | None
    sources: dict[int, tuple[bool, bool]] = field(default_factory=dict)


@dataclass(frozen=True)
class WifiMirror:
    present: bool
    running: bool | None


@dataclass(frozen=True)
class PortsState:
    router_id: str
    switch: str | None
    managed: bool
    ports: tuple[PortView, ...]
    vlans: tuple[VlanView, ...]
    mirror: MirrorView
    wifi_mirror: WifiMirror
    can_disable: bool
    own_reason: OwnReason
    cpu_port: int | None
    max_vlan: int
    own_interface: str | None
    port_count: int


def _unmanaged(router_id: str, wifi_mirror: WifiMirror, own: str | None) -> PortsState:
    return PortsState(
        router_id, None, False, (), (), MirrorView(False, None), wifi_mirror, False, "none", None, 0, own, 0
    )


async def _json(t: Transport, command: str) -> dict[str, object]:
    r = await t.run(command)
    try:
        value = json.loads(r.stdout) if r.ok and r.stdout.strip() else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def read_wifi_mirror(t: Transport) -> WifiMirror:
    listed = await _json(t, c.service_list("wifi-mirror"))
    service = listed.get("wifi-mirror")
    if not isinstance(service, dict):
        return WifiMirror(False, None)
    instances = service.get("instances", {})
    running = isinstance(instances, dict) and any(
        isinstance(i, dict) and i.get("running") for i in instances.values()
    )
    return WifiMirror(True, running)


def _used_by(device: str, net: NetworkState) -> tuple[str, ...]:
    bridges = {d.name for d in net.devices if device in d.ports}
    return tuple(
        v.conf.name for v in net.interfaces if v.conf is not None and v.conf.device in ({device} | bridges)
    )


async def read_ports(
    t: Transport, rec: RouterRecord, desc: SelfDescription, net: NetworkState, uci: dict[str, str]
) -> PortsState:
    wifi_mirror = await read_wifi_mirror(t)
    board = desc.board
    switch = board.switch_name if board else None
    if board is None or switch is None:
        return _unmanaged(rec.id, wifi_mirror, net.own_interface)
    helped = await t.run(c.swconfig_help(switch))
    if not helped.ok:
        return _unmanaged(rec.id, wifi_mirror, net.own_interface)
    help_ = parse_swconfig_help(helped.stdout)
    live = parse_swconfig_show(switch, (await t.run(c.swconfig_show(switch))).stdout)
    arl = parse_arl((await t.run(c.swconfig_arl(switch))).stdout)
    pc_mac = parse_arp((await t.run(c.ARP)).stdout).get(net.pc_ip or "")
    features = await _json(t, c.switch_features(switch))
    cpu = next((p for p in board.ports if p.cpu), None)
    external = [p for p in board.ports if not p.cpu and p.role]
    vlans = []
    for v in (v for v in switch_vlans(uci) if v.device == switch):
        device = f"{cpu.device}.{v.vid or v.vlan}" if cpu and cpu.device else None
        members: dict[int, Cell] = {p: "t" if tagged else "u" for p, tagged in v.members}
        vlans.append(
            VlanView(v.section, v.vlan, v.vid, members, device, _used_by(device, net) if device else ())
        )
    by_num = {p.num: p for p in live.ports}
    own_ports: set[int] = set()
    reason: OwnReason = "none"
    if pc_mac and arl.get(pc_mac) in {p.num for p in external}:
        own_ports, reason = {arl[pc_mac]}, "arl"
    elif net.own_interface:
        own_vlans = [v for v in vlans if net.own_interface in v.used_by]
        linked = {
            p.num
            for p in external
            for v in own_vlans
            if p.num in v.members and by_num.get(p.num) is not None and by_num[p.num].link
        }
        if linked:
            own_ports, reason = linked, "only-link" if len(linked) == 1 else "candidates"
    lock = OWN if reason in ("arl", "only-link") else MAYBE_OWN
    ports = []
    for p in external:
        state = by_num.get(p.num)
        ports.append(
            PortView(
                num=p.num,
                label=rec.port_labels.get(p.num) or p.label or f"port {p.num}",
                role=p.role,
                link=bool(state and state.link),
                speed_mbps=state.speed_mbps if state else None,
                full_duplex=state.full_duplex if state else None,
                enabled=state.enabled if state else None,
                own=p.num in own_ports and reason in ("arl", "only-link"),
                lock=lock if p.num in own_ports else None,
            )
        )
    conf = switch_conf(uci, switch)
    sources = {p.num: (p.mirror_rx, p.mirror_tx) for p in live.ports if p.mirror_rx or p.mirror_tx}
    monitor = conf.mirror_monitor_port if conf and conf.mirror_monitor_port is not None else None
    if monitor is None and sources:
        monitor = live.mirror_monitor_port
    available = (
        bool(features.get("mirror_option"))
        and "mirror_monitor_port" in help_.global_attrs
        and {"enable_mirror_rx", "enable_mirror_tx"} <= help_.port_attrs
    )
    return PortsState(
        router_id=rec.id,
        switch=switch,
        managed=True,
        ports=tuple(sorted(ports, key=lambda p: p.label)),
        vlans=tuple(sorted(vlans, key=lambda v: v.vlan)),
        mirror=MirrorView(available, monitor, sources),
        wifi_mirror=wifi_mirror,
        can_disable="enable" in help_.port_attrs,
        own_reason=reason,
        cpu_port=cpu.num if cpu else help_.cpu_port,
        max_vlan=max(help_.vlans - 1, 0),
        own_interface=net.own_interface,
        port_count=help_.ports,
    )
