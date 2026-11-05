"""The Ports screen's changes (spec 7.5, plan v0.3 "Ports rules"): port enable (runtime swconfig), VLANs and
the switch port mirror (`network` config, applied with the rollback)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.ports.model import Members
from openwrtgui.ports.parse import render_members, switch_conf, switch_ports
from openwrtgui.ports.state import PortsState, PortView
from openwrtgui.uci import UciOp

Cell = Literal["u", "t"]
NOT_MANAGED = "This router's switch is not managed by swconfig"


@dataclass(frozen=True)
class VlanRequest:
    section: str | None  # None: a new VLAN
    vlan: int
    members: Mapping[int, Cell]


@dataclass(frozen=True)
class MirrorRequest:
    monitor: int | None  # None: mirroring off
    sources: Mapping[int, tuple[bool, bool]]  # port → (RX, TX)


def _managed(state: PortsState) -> str:
    if not state.managed or state.switch is None:
        raise ValueError(NOT_MANAGED)
    return state.switch


def _label(state: PortsState, port: int) -> str:
    view = next((p for p in state.ports if p.num == port), None)
    return view.label if view else ("CPU" if port == state.cpu_port else f"port {port}")


def _port(state: PortsState, port: int) -> PortView:
    view = next((p for p in state.ports if p.num == port), None)
    if view is None:
        raise ValueError(f"Port {port} is not a socket of this switch")
    return view


def enable_commands(state: PortsState, port: int, on: bool, router_name: str) -> list[str]:
    switch = _managed(state)
    if not state.can_disable:
        raise ValueError("This switch cannot turn ports off.")
    view = _port(state, port)
    if view.enabled is None:
        raise ValueError(f"{view.label} cannot be turned on or off")
    if not on and view.own:
        raise ValueError(
            f"{view.label} carries this app's SSH to {router_name}; turning it off cuts the app off."
        )
    if not on and view.lock and state.own_reason == "unplaced":
        raise ValueError(
            f"{view.label} may carry this app's SSH to {router_name}: the app cannot tell which socket "
            "its connection uses, so every socket with a link stays on."
        )
    if not on and view.lock:
        linked = sum(1 for p in state.ports if p.lock)
        raise ValueError(
            f"{view.label} may carry this app's SSH to {router_name} "
            f"({linked} ports have a link in its VLAN); it stays on."
        )
    if view.enabled == on:
        return []
    return [f"swconfig dev {switch} port {port} set enable {1 if on else 0}"]


def enable_all_commands(state: PortsState) -> list[str]:
    switch = _managed(state)
    if not state.can_disable:
        raise ValueError("This switch cannot turn ports off.")
    return [f"swconfig dev {switch} port {p.num} set enable 1" for p in state.ports if p.enabled is False]


def _members(req: VlanRequest, ports: int) -> dict[int, bool]:
    members: dict[int, bool] = {}
    for port, cell in req.members.items():
        if not 0 <= port < ports:
            raise ValueError(f"Port {port} is not on this switch")
        members[port] = cell == "t"
    return members


def compile_vlans(
    upserts: Sequence[VlanRequest], deletes: Sequence[str], state: PortsState
) -> tuple[list[UciOp], list[str]]:
    switch = _managed(state)
    by_section = {v.section: v for v in state.vlans}
    for section in deletes:
        vlan = by_section.get(section)
        if vlan is None:
            raise ValueError(f"There is no VLAN {section}")
        if vlan.used_by:
            used = vlan.used_by[0]
            raise ValueError(
                f"VLAN {vlan.vlan} carries {used} ({vlan.device}). Move {used} to another device first."
            )
    edited = {u.section for u in upserts if u.section}
    final: dict[int, Members] = {
        v.vlan: tuple((p, c == "t") for p, c in v.members.items())
        for v in state.vlans
        if v.section not in edited and v.section not in deletes
    }
    ops: list[UciOp] = []
    warnings: list[str] = []
    for n, req in enumerate(upserts, 1):
        if req.section is not None and req.section not in by_section:
            raise ValueError(f"There is no VLAN {req.section}")
        if not 1 <= req.vlan <= state.max_vlan:
            raise ValueError(f"VLAN numbers on this switch are 1 to {state.max_vlan}")
        if req.vlan in final:
            raise ValueError(f"There is already a VLAN {req.vlan}")
        members = _members(req, state.port_count)
        final[req.vlan] = tuple(sorted(members.items()))
        if state.cpu_port is not None and state.cpu_port not in members:
            warnings.append(f"VLAN {req.vlan} has no CPU port: the router cannot reach it.")
        old = by_section.get(req.section or "")
        own = state.own_interface
        if old is not None and own and own in old.used_by:
            warnings.append(
                f"VLAN {req.vlan} carries {own}, this app's connection; "
                "the change applies with a 60 s rollback."
            )
        if req.section is None:
            p = f"network.$v{n}"
            ops += [UciOp("add", p, "switch_vlan"), UciOp("set", f"{p}.device", switch)]
        else:
            p = f"network.{req.section}"
        ops += [UciOp("set", f"{p}.vlan", str(req.vlan)), UciOp("set", f"{p}.ports", render_members(members))]
    untagged: dict[int, int] = {}
    for number, members_of in sorted(final.items()):
        for port, tagged in members_of:
            if tagged:
                continue
            if port in untagged:
                raise ValueError(
                    f"Port {_label(state, port)} is untagged in VLAN {untagged[port]} and VLAN {number}; "
                    "a port is untagged in one VLAN at most."
                )
            untagged[port] = number
    ops += [UciOp("delete", f"network.{s}") for s in deletes]
    return ops, warnings


def compile_mirror(req: MirrorRequest, state: PortsState, uci: Mapping[str, str]) -> list[UciOp]:
    switch = _managed(state)
    if not state.mirror.available:
        raise ValueError("This switch has no port mirroring.")
    conf = switch_conf(uci, switch)
    if conf is None:
        raise ValueError(f"/etc/config/network has no section for {switch}")
    sources = (
        {p: flags for p, flags in req.sources.items() if flags[0] or flags[1]}
        if req.monitor is not None
        else {}
    )
    if req.monitor is not None:
        _port(state, req.monitor)
        if req.monitor in sources:
            raise ValueError(f"{_label(state, req.monitor)} is the monitor port; it cannot also be a source.")
    for port in sources:
        _port(state, port)
    p = f"network.{conf.section}.mirror_monitor_port"
    ops = [UciOp("set", p, str(req.monitor)) if req.monitor is not None else UciOp("delete", p)]
    existing = {sp.port: sp.section for sp in switch_ports(uci) if sp.device == switch}
    new = 0
    for port in sorted(set(existing) | set(sources)):
        rx, tx = sources.get(port, (False, False))
        if port in existing:
            s = f"network.{existing[port]}"
        elif rx or tx:
            new += 1
            s = f"network.$s{new}"
            ops += [
                UciOp("add", s, "switch_port"),
                UciOp("set", f"{s}.device", switch),
                UciOp("set", f"{s}.port", str(port)),
            ]
        else:
            continue
        for name, on in (("enable_mirror_rx", rx), ("enable_mirror_tx", tx)):
            ops.append(UciOp("set", f"{s}.{name}", "1") if on else UciOp("delete", f"{s}.{name}"))
    return ops
