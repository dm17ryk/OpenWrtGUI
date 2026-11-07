"""Firewall changes as uci operations: the filtering model per zone and direction with the pins that keep the
app's own path open (spec 7.6, D11), zones and forwardings."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from openwrtgui.fw.model import DIRECTIONS, Direction, FirewallConf, Policy, ZoneConf
from openwrtgui.fw.parse import POLICIES, ZONE_FIELDS
from openwrtgui.fw.state import NOT_FW4, PIN_DHCP, PIN_SSH, FirewallState, rule_effect
from openwrtgui.net.apply import ROLLBACK_S
from openwrtgui.net.state import NetworkState
from openwrtgui.uci import UciOp

_ZONE = re.compile(r"[A-Za-z0-9_]{1,11}")
_OPTION = re.compile(r"[a-z0-9_]+")
PIN_WARNINGS = {
    "ssh": (
        "Without this rule the app loses {router} as soon as the change applies. "
        f"The {ROLLBACK_S} s rollback then restores the old firewall by itself."
    ),
    "dhcpdns": (
        "Without this rule devices on {zone} stop getting addresses and names from {router}, "
        "including the panels under test."
    ),
}


@dataclass(frozen=True)
class ModelRequest:
    cells: Mapping[str, Policy]  # "<zone>.<direction>" -> the policy asked
    pins_removed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ZoneRequest:
    section: str | None  # None: a new zone
    name: str
    networks: tuple[str, ...]
    input: Policy
    output: Policy
    forward: Policy
    masq: bool
    mtu_fix: bool
    others: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ForwardingRequest:
    src: str
    dest: str


def require_fw4(state: FirewallState) -> None:
    if not state.available:
        raise ValueError(NOT_FW4)


def check_zone_name(name: str) -> None:
    if not _ZONE.fullmatch(name):
        raise ValueError("A zone name is 1 to 11 letters, digits or _")


def check_others(others: Mapping[str, str | None], fields: frozenset[str]) -> None:
    for name in others:
        if not _OPTION.fullmatch(name):
            raise ValueError(f"{name} is not an option name")
        if name in fields:
            raise ValueError(f"{name} has its own field")


def _others(path: str, others: Mapping[str, str | None]) -> list[UciOp]:
    return [
        UciOp("delete", f"{path}.{k}") if v is None else UciOp("set", f"{path}.{k}", v)
        for k, v in others.items()
    ]


def _summary(n: int) -> str:
    rules = "1 rule no longer does anything" if n == 1 else f"{n} rules no longer do anything"
    return (
        f"{rules} in this model. They stay in the config, so switching back restores them; "
        "delete them here if you no longer need them."
    )


def _pin_ops(pin: str, zone: str, state: FirewallState) -> list[UciOp]:
    if pin == "ssh":
        if not state.pc_ip:
            raise ValueError("Could not tell this PC's address, so the app cannot keep its own SSH open.")
        p = f"firewall.{PIN_SSH}"
        values = {"name": "Allow SSH from this PC", "src": zone, "src_ip": state.pc_ip, "proto": "tcp"}
        values |= {"dest_port": str(state.ssh_port), "target": "ACCEPT"}
    else:
        p = f"firewall.{PIN_DHCP}"
        values = {"name": "Allow DHCP and DNS", "src": zone, "proto": "udp tcp", "dest_port": "53 67 68"}
        values |= {"target": "ACCEPT"}
    return [UciOp("set", p, "rule"), *(UciOp("set", f"{p}.{k}", v) for k, v in values.items())]


def with_policy(zone: ZoneConf, direction: Direction, policy: Policy) -> ZoneConf:
    if direction == "input":
        return replace(zone, input=policy)
    if direction == "forward":
        return replace(zone, forward=policy)
    return replace(zone, output=policy)


def compile_model(req: ModelRequest, state: FirewallState, router_name: str) -> tuple[list[UciOp], list[str]]:
    require_fw4(state)
    conf = state.conf
    ops: list[UciOp] = []
    zones = {z.name: z for z in conf.zones}
    for key, policy in req.cells.items():
        name, _, direction = key.partition(".")
        zone = zones.get(name)
        if zone is None:
            raise ValueError(f"There is no zone named {name}")
        if direction not in DIRECTIONS:
            raise ValueError(f"{direction} is not input, forward or output")
        if policy not in POLICIES:
            raise ValueError(f"{policy} is not ACCEPT, REJECT or DROP")
        ops.append(UciOp("set", f"firewall.{zone.section}.{direction}", policy))
        zones[name] = with_policy(zone, direction, policy)
    warnings: list[str] = []
    own = zones.get(state.own_zone or "")
    blocking = own is not None and own.input != "ACCEPT"
    for pin in state.pins:
        section = f"firewall.{PIN_SSH if pin.id == 'ssh' else PIN_DHCP}"
        if pin.id in req.pins_removed:
            if pin.present:
                ops.append(UciOp("delete", section))
            warnings.append(PIN_WARNINGS[pin.id].format(router=router_name, zone=state.own_zone))
        elif blocking and own is not None:
            ops += _pin_ops(pin.id, own.name, state)
    after = replace(conf, zones=tuple(zones[z.name] for z in conf.zones))
    dead = sum(1 for r in conf.rules if rule_effect(r, after).effect.startswith("no-effect"))
    if dead and req.cells:
        warnings.append(_summary(dead))
    return ops, warnings


def _count(n: int, what: str) -> str | None:
    return None if n == 0 else f"1 {what}" if n == 1 else f"{n} {what}s"


def in_use(
    conf: FirewallConf, name: str, forwardings: Sequence[ForwardingRequest] | None = None
) -> str | None:
    """What refers to zone `name`; `forwardings` are the ones a request puts in place of the current ones."""
    fwd = conf.forwardings if forwardings is None else forwardings
    parts = [
        p
        for p in (
            _count(sum(1 for r in conf.rules if name in (r.src, r.dest)), "rule"),
            _count(sum(1 for f in fwd if name in (f.src, f.dest)), "forwarding"),
            _count(sum(1 for r in conf.redirects if name in (r.src, r.dest)), "port forward"),
            _count(sum(1 for n in conf.nats if n.src == name), "NAT rule"),
        )
        if p
    ]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def _refuse_in_use(
    conf: FirewallConf, name: str, forwardings: Sequence[ForwardingRequest] | None = None
) -> None:
    if used := in_use(conf, name, forwardings):
        raise ValueError(f"Zone {name} is used by {used}; delete or move them first.")


def _zone_ops(p: str, req: ZoneRequest, zone: ZoneConf | None) -> list[UciOp]:
    ops: list[UciOp] = []
    if zone is None or req.name != zone.name:
        ops.append(UciOp("set", f"{p}.name", req.name))
    if zone is None or req.networks != zone.networks:
        ops += [
            UciOp("delete", f"{p}.network"),
            *(UciOp("add_list", f"{p}.network", n) for n in req.networks),
        ]
    for direction in DIRECTIONS:
        policy = cast(Policy, getattr(req, direction))
        if policy not in POLICIES:
            raise ValueError(f"{policy} is not ACCEPT, REJECT or DROP")
        ops.append(UciOp("set", f"{p}.{direction}", policy))
    for flag in ("masq", "mtu_fix"):
        ops.append(UciOp("set", f"{p}.{flag}", "1") if getattr(req, flag) else UciOp("delete", f"{p}.{flag}"))
    return ops + _others(p, req.others)


def compile_zones(
    upserts: Sequence[ZoneRequest],
    deletes: Sequence[str],
    forwardings: Sequence[ForwardingRequest] | None,
    state: FirewallState,
    net: NetworkState,
    router_name: str,
) -> list[UciOp]:
    require_fw4(state)
    conf = state.conf
    by_section = {z.section: z for z in conf.zones}
    names = {z.name for z in conf.zones}
    ops: list[UciOp] = []
    for section in deletes:
        zone = by_section.get(section)
        if zone is None:
            raise ValueError(f"There is no zone {section}")
        if zone.name == state.own_zone:
            raise ValueError(
                f"{zone.name} carries this app's connection to {router_name}; it cannot be deleted here."
            )
        _refuse_in_use(conf, zone.name)
        names.discard(zone.name)
    new = 0
    for req in upserts:
        zone = by_section.get(req.section) if req.section else None
        if req.section and zone is None:
            raise ValueError(f"There is no zone {req.section}")
        check_zone_name(req.name)
        if (zone is None or req.name != zone.name) and req.name in names:
            raise ValueError(f"There is already a zone named {req.name}")
        if zone is not None and req.name != zone.name:  # forwardings sent along may move to the new name
            _refuse_in_use(conf, zone.name, forwardings)
        own = net.own_interface
        if zone is not None and zone.name == state.own_zone and own and own not in req.networks:
            raise ValueError(f"{own} carries this app's connection; it stays in zone {zone.name}.")
        for n in req.networks:
            if net.conf(n) is None:
                raise ValueError(f"There is no interface named {n}")
        check_others(req.others, ZONE_FIELDS)
        names.add(req.name)
        if zone is None:
            new += 1
            p = f"firewall.$z{new}"
            ops += [UciOp("add", p, "zone"), *_zone_ops(p, req, None)]
        else:
            ops += _zone_ops(f"firewall.{zone.section}", req, zone)
    if forwardings is not None:
        want = {(f.src, f.dest) for f in forwardings}
        for src, dest in want:
            for zone_name in (src, dest):
                if zone_name not in names:
                    raise ValueError(f"There is no zone named {zone_name}")
        have = {(f.src, f.dest) for f in conf.forwardings}
        ops += [
            UciOp("delete", f"firewall.{f.section}") for f in conf.forwardings if (f.src, f.dest) not in want
        ]
        for i, (src, dest) in enumerate(sorted(want - have), start=1):
            p = f"firewall.$f{i}"
            ops += [
                UciOp("add", p, "forwarding"),
                UciOp("set", f"{p}.src", src),
                UciOp("set", f"{p}.dest", dest),
            ]
    ops += [UciOp("delete", f"firewall.{s}") for s in deletes]
    return ops


def zone_policies(upserts: Sequence[ZoneRequest]) -> list[tuple[str, Direction, Policy]]:
    return [(z.name, d, cast(Policy, getattr(z, d))) for z in upserts for d in DIRECTIONS]
