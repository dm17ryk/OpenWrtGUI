"""The VLAN editor's rules (v1.0a3 D2, D3 layer 1) and its uci ops. Only bridge-vlan sections are written:
never a device's ports or vlan_filtering, never an interface."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from openwrtgui.ports.bridge import (
    MAX_VLAN,
    MIN_VLAN,
    BridgeState,
    BridgeVlanView,
    Cell,
    LiveVlan,
    natural,
    netifd_spec,
    parse_spec,
    render_spec,
)
from openwrtgui.uci import UciOp

_PORT = re.compile(r"[A-Za-z0-9_.@-]{1,15}")  # an interface name (IFNAMSIZ): it reaches a uci value


@dataclass(frozen=True)
class BridgeVlanRequest:
    section: str | None  # None: a new VLAN
    vlan: int
    members: Mapping[str, Cell]
    local: bool = True


@dataclass(frozen=True)
class BridgeChange:
    ops: tuple[UciOp, ...]
    warnings: tuple[str, ...]
    want: tuple[LiveVlan, ...]  # every VLAN of the bridge as netifd should report it after the change


@dataclass(frozen=True)
class _Final:
    local: bool
    entries: dict[str, str]  # port -> entry


def _editable(state: BridgeState) -> str:
    if state.bridge is None:
        raise ValueError("This router has no bridge with VLAN filtering")
    if not state.editable:
        raise ValueError(state.blocker or f"The VLANs of {state.bridge} are read only here")
    return state.bridge


def _deletable(by_section: Mapping[str, BridgeVlanView], section: str, bridge: str) -> None:
    v = by_section.get(section)
    if v is None:
        raise ValueError(f"There is no VLAN {section}")
    if v.used_by:  # D2 c: LuCI does not check
        iface = v.used_by[0]
        raise ValueError(
            f"VLAN {v.vlan} carries {iface} ({bridge}.{v.vlan}). Move {iface} to another device first."
        )


def _checked(
    req: BridgeVlanRequest,
    by_section: Mapping[str, BridgeVlanView],
    final: Mapping[int, _Final],
    state: BridgeState,
) -> BridgeVlanView | None:
    own = state.own_interface
    old = by_section.get(req.section) if req.section is not None else None
    if req.section is not None and old is None:
        raise ValueError(f"There is no VLAN {req.section}")
    if old is not None and old.vlan != req.vlan:  # D2 b
        raise ValueError(
            f"VLAN {old.vlan} keeps its number here: add VLAN {req.vlan} and remove VLAN {old.vlan} instead."
        )
    if not MIN_VLAN <= req.vlan <= MAX_VLAN:
        raise ValueError(f"VLAN numbers are {MIN_VLAN} to {MAX_VLAN}")
    if req.vlan in final:
        raise ValueError(f"There is already a VLAN {req.vlan}")
    sectionless = not any(v.vlan == state.own_vlan for v in state.vlans)
    if old is None and req.vlan == state.own_vlan and sectionless:  # final review Important 2a
        raise ValueError(
            f"VLAN {req.vlan} carries {own}, this app's connection, but has no bridge-vlan section here: "
            "adding one could leave this PC's port or the router out of it. Set it up in LuCI."
        )
    if old is not None and old.own and not req.local:  # D3 layer 1
        raise ValueError(
            f"VLAN {old.vlan} carries {own}, this app's connection: the router stays in it, "
            "so local stays on."
        )
    return old


def _entries(
    req: BridgeVlanRequest, old: BridgeVlanView | None, ports: set[str], bridge: str
) -> dict[str, str]:
    """The request's members as entries: a cell the user did not change keeps its text (D2 a)."""
    out: dict[str, str] = {}
    for port, cell in req.members.items():
        if port not in ports or not _PORT.fullmatch(port):
            raise ValueError(f"{port} is not a port of {bridge}")
        if old is not None and old.members.get(port) == cell:
            out[port] = old.entries[port]
        else:
            out[port] = render_spec(port, cell)
    return out


def _upsert_ops(
    n: int, req: BridgeVlanRequest, old: BridgeVlanView | None, entries: Mapping[str, str], bridge: str
) -> list[UciOp]:
    listed = sorted(entries.values(), key=natural)  # LuCI sorts the entries
    local = "1" if req.local else "0"
    if old is None:
        p = f"network.$b{n}"
        return [
            UciOp("add", p, "bridge-vlan"),
            UciOp("set", f"{p}.device", bridge),
            UciOp("set", f"{p}.vlan", str(req.vlan)),
            UciOp("set", f"{p}.local", local),
            *(UciOp("add_list", f"{p}.ports", e) for e in listed),
        ]
    p = f"network.{old.section}"
    ops = [UciOp("set", f"{p}.local", local)] if req.local != old.local else []
    if listed != sorted(old.entries.values(), key=natural):
        ops += [UciOp("delete", f"{p}.ports"), *(UciOp("add_list", f"{p}.ports", e) for e in listed)]
    return ops


def _warnings(
    req: BridgeVlanRequest, old: BridgeVlanView | None, entries: Mapping[str, str], own: str | None
) -> list[str]:
    out = [f"VLAN {req.vlan} has no ports."] if not entries else []
    if old is not None and old.own:
        out.append(
            f"VLAN {req.vlan} carries {own}, this app's connection; the change applies with a 60 s rollback."
        )
    if old is not None and old.local and not req.local:
        out += [
            f"VLAN {req.vlan} carries {iface}: with local off the router leaves VLAN {req.vlan}, "
            f"so {iface} gets no traffic."
            for iface in old.used_by
        ]
    return out


def _untagged_once(final: Mapping[int, _Final]) -> None:
    seen: dict[str, int] = {}
    for vlan, f in sorted(final.items()):
        for spec in filter(None, map(parse_spec, f.entries.values())):
            if not spec.untagged:
                continue
            if spec.port in seen:
                raise ValueError(
                    f"{spec.port} is untagged in VLAN {seen[spec.port]} and VLAN {vlan}; "
                    "a port is untagged in one VLAN at most."
                )
            seen[spec.port] = vlan


def _own_path_kept(state: BridgeState, final: Mapping[int, _Final], router_name: str) -> None:
    """D3 layer 1, the management-path rule. The app cannot tell which port is the PC's (the own-port lock by
    the bridge FDB is 1.x), so the rollback catches a change to the PC's port while another linked port
    stays."""
    if state.own_vlan is None:
        return
    carry = [p.name for p in state.ports if p.may_carry]
    before = next((v for v in state.vlans if v.vlan == state.own_vlan), None)
    if not carry or before is None:
        return
    after = final.get(state.own_vlan)
    kept = [p for p in carry if after is not None and after.entries.get(p) == before.entries.get(p)]
    if not kept:
        raise ValueError(
            f"{', '.join(carry)} may carry this app's SSH to {router_name} (the ports with a link in "
            f"VLAN {state.own_vlan}, which carries {state.own_interface}): one of them keeps its "
            f"VLAN {state.own_vlan} membership as it is."
        )


def _want(final: Mapping[int, _Final]) -> tuple[LiveVlan, ...]:
    return tuple(
        LiveVlan(vlan, f.local, frozenset(filter(None, map(netifd_spec, f.entries.values()))))
        for vlan, f in sorted(final.items())
    )


def bridge_change(
    state: BridgeState, upserts: Sequence[BridgeVlanRequest], deletes: Sequence[str], router_name: str
) -> BridgeChange:
    bridge = _editable(state)
    by_section = {v.section: v for v in state.vlans}
    for section in deletes:
        _deletable(by_section, section, bridge)
    gone = {u.section for u in upserts if u.section} | set(deletes)
    final = {v.vlan: _Final(v.local, dict(v.entries)) for v in state.vlans if v.section not in gone}
    ports = {p.name for p in state.ports}
    ops: list[UciOp] = []
    warnings: list[str] = []
    for n, req in enumerate(upserts, 1):
        old = _checked(req, by_section, final, state)
        entries = _entries(req, old, ports, bridge)
        final[req.vlan] = _Final(req.local, entries)
        ops += _upsert_ops(n, req, old, entries, bridge)
        warnings += _warnings(req, old, entries, state.own_interface)
    _untagged_once(final)
    _own_path_kept(state, final, router_name)
    ops += [UciOp("delete", f"network.{s}") for s in deletes]
    return BridgeChange(tuple(ops), tuple(warnings), _want(final))
