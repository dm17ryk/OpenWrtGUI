"""The firewall as the screen shows it: fw4's config, each rule's effect in the model, the pins that keep the
app's own path open, every other nft table and tc hook with its owner, and live counters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.fw import commands as c
from openwrtgui.fw.model import Direction, FirewallConf, FwRuleConf
from openwrtgui.fw.nft import Ruleset, parse_ruleset_json
from openwrtgui.fw.owners import NftObject, TcHook, nft_objects, tc_hooks
from openwrtgui.fw.parse import firewall_conf
from openwrtgui.fw.tc import parse_qdiscs
from openwrtgui.net.state import NetworkState
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.store.settings import KnownTable
from openwrtgui.transport.base import Transport
from openwrtgui.uci import parse_uci_show

NOT_FW4 = "This router does not run fw4 (firewall4); its firewall is not managed here."
TargetClass = Literal["accept", "block", "other"]
Effect = Literal["allows", "blocks", "no-effect-allow", "no-effect-block", "other"]
PIN_SSH = "owg_pin_ssh"
PIN_DHCP = "owg_pin_dhcpdns"


@dataclass(frozen=True)
class RuleView:
    conf: FwRuleConf
    direction: Direction | None
    zone: str | None
    target_class: TargetClass
    effect: Effect
    packets: int | None


@dataclass(frozen=True)
class PinView:
    id: Literal["ssh", "dhcpdns"]
    name: str
    match: str
    why: str
    present: bool


@dataclass(frozen=True)
class FirewallState:
    router_id: str
    available: bool
    reason: str | None
    conf: FirewallConf
    rules: tuple[RuleView, ...]
    own_zone: str | None
    pc_ip: str | None
    ssh_port: int
    pins: tuple[PinView, ...]
    objects: tuple[NftObject, ...]
    tc: tuple[TcHook, ...]
    counters: dict[str, int]


def target_class(target: str) -> TargetClass:
    return "accept" if target == "ACCEPT" else "block" if target in ("REJECT", "DROP") else "other"


def rule_effect(rule: FwRuleConf, conf: FirewallConf, packets: int | None = None) -> RuleView:
    """What a rule does in the zones' model: a rule whose class equals the default it meets does nothing."""
    cls = target_class(rule.target)
    direction: Direction | None = None
    zone: str | None = None
    default: str | None = None
    if rule.src == "*" or rule.dest == "*" or (rule.src is None and rule.dest is None):
        pass
    elif rule.src is not None and rule.dest is None:
        direction, zone = "input", rule.src
        default = z.input if (z := conf.zone(zone)) else None
    elif rule.src is not None:
        direction, zone = "forward", rule.src
        forwarded = any(f.enabled and f.src == rule.src and f.dest == rule.dest for f in conf.forwardings)
        default = "ACCEPT" if forwarded else (z.forward if (z := conf.zone(zone)) else None)
    else:
        direction, zone = "output", rule.dest
        default = z.output if (z := conf.zone(zone)) else None
    effect: Effect = "other"
    if rule.enabled and cls != "other" and default is not None:
        same = target_class(default) == cls
        effect = (
            ("no-effect-allow" if cls == "accept" else "no-effect-block")
            if same
            else ("allows" if cls == "accept" else "blocks")
        )
    return RuleView(rule, direction, zone, cls, effect, packets)


def own_zone(conf: FirewallConf, net: NetworkState) -> str | None:
    if net.own_interface is None:
        return None
    return next((z.name for z in conf.zones if net.own_interface in z.networks), None)


def serves_dhcp(conf: FirewallConf, zone: str | None, net: NetworkState) -> bool:
    z = conf.zone(zone)
    return z is not None and any(d.enabled and d.interface in z.networks for d in net.dhcp)


def pins(
    conf: FirewallConf, uci: Mapping[str, str], net: NetworkState, router_name: str, ssh_port: int
) -> list[PinView]:
    zone = own_zone(conf, net)
    if zone is None:
        return []
    out = [
        PinView(
            "ssh",
            "Allow SSH from this PC",
            f"{zone} → this router · {net.pc_ip} · tcp {ssh_port}",
            f"how this app reaches {router_name}",
            f"firewall.{PIN_SSH}" in uci,
        )
    ]
    if serves_dhcp(conf, zone, net):
        out.append(
            PinView(
                "dhcpdns",
                "Allow DHCP and DNS",
                f"{zone} → this router · udp 67-68, udp/tcp 53",
                f"{router_name} serves DHCP and DNS on {zone}",
                f"firewall.{PIN_DHCP}" in uci,
            )
        )
    return out


def counters(ruleset: Ruleset) -> dict[str, int]:
    """Packets per fw4 rule name (`!fw4: <name>`)."""
    out: dict[str, int] = {}
    for r in ruleset.rules:
        if r.comment and r.comment.startswith("!fw4: ") and r.packets is not None:
            name = r.comment.removeprefix("!fw4: ")
            out[name] = out.get(name, 0) + r.packets
    return out


def available(desc: SelfDescription) -> bool:
    return bool((desc.features or {}).get("firewall4"))


async def read_firewall(
    t: Transport,
    router_id: str,
    router_name: str,
    ssh_port: int,
    desc: SelfDescription,
    net: NetworkState,
    known: Sequence[KnownTable],
    app_devices: frozenset[str] = frozenset(),
) -> tuple[FirewallState, dict[str, str], Ruleset]:
    uci = parse_uci_show((await t.run(c.UCI_FIREWALL)).stdout)
    conf = firewall_conf(uci)
    ruleset = (
        parse_ruleset_json((await t.run(c.NFT_JSON)).stdout) if available(desc) else Ruleset((), (), (), ())
    )
    qdiscs = parse_qdiscs((await t.run(c.TC_QDISCS)).stdout)
    packets = counters(ruleset)
    state = FirewallState(
        router_id=router_id,
        available=available(desc),
        reason=None if available(desc) else NOT_FW4,
        conf=conf,
        rules=tuple(rule_effect(r, conf, packets.get(r.name or "")) for r in conf.rules),
        own_zone=own_zone(conf, net),
        pc_ip=net.pc_ip,
        ssh_port=ssh_port,
        pins=tuple(pins(conf, uci, net, router_name, ssh_port)),
        objects=tuple(nft_objects(ruleset, known)),
        tc=tuple(tc_hooks(qdiscs, app_devices)),
        counters=packets,
    )
    return state, uci, ruleset
