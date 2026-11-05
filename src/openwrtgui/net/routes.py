"""Static routes and policy rules (spec 7.4, the LuCI Routing page), and the live routing table.

Every change is a `network` change, so it applies with the rollback: a route or a rule can cut the app's
own path as surely as an address can.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.net import commands as c
from openwrtgui.net.model import Family, LiveRoute, LiveRule, parse_cidr
from openwrtgui.net.parse import parse_ip_routes, parse_ip_rules
from openwrtgui.net.state import NetworkState
from openwrtgui.transport.base import Transport
from openwrtgui.uci import UciOp

RULE_ACTIONS = ("prohibit", "unreachable", "blackhole", "throw")
FAMILIES: tuple[Family, ...] = (4, 6)
RAW = "ip -4 route show table all; ip -6 route show table all; ip -4 rule show; ip -6 rule show"


@dataclass(frozen=True)
class RouteRequest:
    section: str | None  # None: a new route
    kind: Literal["route", "route6"]
    interface: str
    target: str
    gateway: str | None = None
    metric: int | None = None
    table: str | None = None
    type: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class RuleRequest:
    section: str | None  # None: a new rule
    kind: Literal["rule", "rule6"]
    src: str | None = None
    dest: str | None = None
    in_iface: str | None = None
    out_iface: str | None = None
    lookup: str | None = None
    priority: int | None = None
    action: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class LiveTables:
    routes: tuple[LiveRoute, ...]
    rules: tuple[LiveRule, ...]
    raw: str | None  # the text tables when this router's `ip` has no JSON output


def family_of(kind: str) -> Family:
    return 6 if kind.endswith("6") else 4


def _address(text: str, family: Family) -> str:
    try:
        ip = ipaddress.ip_address(text.strip())
    except ValueError:
        ip = None
    if ip is None or ip.version != family:
        raise ValueError(f"{text} is not an IPv{family} address")
    return str(ip)


def _network(text: str, family: Family) -> str:
    """A rule's source or destination: a network, or one address."""
    try:
        net = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError:
        net = None
    if net is None or net.version != family:
        raise ValueError(f"{text} is not an IPv{family} network (address/prefix)")
    return text.strip()


def _interface(state: NetworkState, name: str) -> str:
    if state.conf(name) is None:
        raise ValueError(f"There is no interface named {name}")
    return name


def _fields(p: str, values: Mapping[str, str | None], new: bool) -> list[UciOp]:
    ops = []
    for key, value in values.items():
        if value:
            ops.append(UciOp("set", f"{p}.{key}", value))
        elif not new:
            ops.append(UciOp("delete", f"{p}.{key}"))
    return ops


def _route_ops(r: RouteRequest, state: NetworkState, var: str) -> list[UciOp]:
    family = family_of(r.kind)
    target = str(parse_cidr(r.target, family))
    if r.metric is not None and r.metric < 0:
        raise ValueError("A metric is 0 or more")
    values = {
        "interface": _interface(state, r.interface),
        "target": target,
        "gateway": _address(r.gateway, family) if r.gateway else None,
        "metric": str(r.metric) if r.metric is not None else None,
        "table": r.table or None,
        "type": r.type or None,
        "disabled": "1" if r.disabled else None,
    }
    if r.section is None:
        p = f"network.${var}"
        return [UciOp("add", p, r.kind), *_fields(p, values, new=True)]
    p = f"network.{r.section}"
    return [*_fields(p, values, new=False), UciOp("delete", f"{p}.netmask")]


def _rule_ops(r: RuleRequest, state: NetworkState, var: str) -> list[UciOp]:
    family = family_of(r.kind)
    if r.action and r.action not in RULE_ACTIONS:
        raise ValueError(f"A rule's action is {', '.join(RULE_ACTIONS)}")
    if r.priority is not None and not 0 <= r.priority <= 32765:
        raise ValueError("A rule's priority is 0 to 32765")
    values = {
        "src": _network(r.src, family) if r.src else None,
        "dest": _network(r.dest, family) if r.dest else None,
        "in": _interface(state, r.in_iface) if r.in_iface else None,
        "out": _interface(state, r.out_iface) if r.out_iface else None,
        "lookup": r.lookup or None,
        "priority": str(r.priority) if r.priority is not None else None,
        "action": r.action or None,
        "disabled": "1" if r.disabled else None,
    }
    if r.section is None:
        p = f"network.${var}"
        return [UciOp("add", p, r.kind), *_fields(p, values, new=True)]
    return _fields(f"network.{r.section}", values, new=False)


def compile_routes(
    upserts: Sequence[RouteRequest],
    deletes: Sequence[str],
    rule_upserts: Sequence[RuleRequest],
    rule_deletes: Sequence[str],
    state: NetworkState,
) -> list[UciOp]:
    known_routes = {r.section for r in state.routes}
    known_rules = {r.section for r in state.rules}
    for section in [*deletes, *(r.section for r in upserts if r.section)]:
        if section not in known_routes:
            raise ValueError(f"There is no route {section}")
    for section in [*rule_deletes, *(r.section for r in rule_upserts if r.section)]:
        if section not in known_rules:
            raise ValueError(f"There is no rule {section}")
    ops: list[UciOp] = []
    for n, route in enumerate(upserts, 1):
        ops += _route_ops(route, state, f"r{n}")
    for n, rule in enumerate(rule_upserts, 1):
        ops += _rule_ops(rule, state, f"p{n}")
    ops += [UciOp("delete", f"network.{s}") for s in [*deletes, *rule_deletes]]
    return ops


@dataclass(frozen=True)
class Expect:
    """One proof for the live table: a route (target, gateway, device) or a rule (priority), there or gone."""

    name: str
    present: bool
    dst: str | None = None
    gateway: str | None = None
    dev: str | None = None
    priority: int | None = None

    def holds(self, live: LiveTables) -> bool:
        if self.priority is not None:
            found = any(x.priority == self.priority for x in live.rules)
        else:
            found = any(
                x.dst == self.dst
                and (self.gateway is None or x.gateway == self.gateway)
                and (self.dev is None or x.dev == self.dev)
                for x in live.routes
            )
        return found == self.present


def expectations(
    state: NetworkState,
    upserts: Sequence[RouteRequest],
    deletes: Sequence[str],
    rule_upserts: Sequence[RuleRequest],
    rule_deletes: Sequence[str],
) -> list[Expect]:
    devices = {v.live.name: v.live.device for v in state.interfaces if v.live is not None}
    out = [
        Expect(f"route {t}", True, dst=t, gateway=r.gateway, dev=devices.get(r.interface))
        for r in upserts
        if not r.disabled
        for t in [str(parse_cidr(r.target, family_of(r.kind)))]
    ]
    out += [
        Expect(f"route {old.target}", False, dst=old.target, gateway=old.gateway)
        for old in state.routes
        if old.section in deletes and not old.disabled
    ]
    out += [
        Expect(f"rule {r.priority}", True, priority=r.priority)
        for r in rule_upserts
        if r.priority is not None and not r.disabled
    ]
    out += [
        Expect(f"rule {old.priority}", False, priority=old.priority)
        for old in state.rules
        if old.section in rule_deletes and old.priority is not None
    ]
    return out


async def read_live(t: Transport) -> LiveTables:
    """`ip -j` routes and rules for both families; the text tables when `ip` has no JSON (busybox ip)."""
    routes: list[LiveRoute] = []
    rules: list[LiveRule] = []
    for family in FAMILIES:
        got = await t.run(c.ip_routes(family))
        got_rules = await t.run(c.ip_rules(family))
        if not (got.ok and got_rules.ok):
            raw = await t.run(RAW)
            return LiveTables((), (), raw.stdout)
        routes += parse_ip_routes(got.stdout, family)
        rules += parse_ip_rules(got_rules.stdout, family)
    return LiveTables(tuple(routes), tuple(rules), None)
