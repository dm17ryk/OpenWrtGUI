"""`uci -X show firewall` → FirewallConf, with fw4's defaults for what a section leaves unset."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openwrtgui.fw.model import (
    DefaultsConf,
    FirewallConf,
    ForwardingConf,
    FwRuleConf,
    IncludeConf,
    IpsetConf,
    NatConf,
    Policy,
    RedirectConf,
    ZoneConf,
)
from openwrtgui.net.parse import options, sections

POLICIES = ("ACCEPT", "REJECT", "DROP")
ZONE_FIELDS = frozenset({"name", "network", "input", "output", "forward", "masq", "mtu_fix"})
RULE_FIELDS = frozenset(
    {
        "name",
        "src",
        "dest",
        "proto",
        "src_ip",
        "dest_ip",
        "src_port",
        "dest_port",
        "icmp_type",
        "family",
        "target",
        "enabled",
    }
)
REDIRECT_FIELDS = frozenset(
    {"name", "src", "src_dport", "dest", "dest_ip", "dest_port", "proto", "target", "enabled"}
)
NAT_FIELDS = frozenset(
    {"name", "src", "src_ip", "dest_ip", "dest_port", "proto", "target", "snat_ip", "snat_port", "enabled"}
)
IPSET_FIELDS = frozenset({"name", "family", "match", "entry", "enabled"})


def _policy(value: str | None, fallback: str) -> Policy:
    value = (value or fallback).upper()
    return cast(Policy, value if value in POLICIES else "DROP")


def _items(value: str | None) -> tuple[str, ...]:
    return tuple(value.split()) if value else ()


def _on(o: Mapping[str, str], name: str) -> bool:
    return o.get(name, "1") != "0"


def _others(o: Mapping[str, str], known: frozenset[str]) -> dict[str, str]:
    return {k: v for k, v in o.items() if k not in known}


def firewall_conf(uci: Mapping[str, str]) -> FirewallConf:
    defaults_sections = sections(uci, "firewall", "defaults")
    defaults = (
        DefaultsConf(defaults_sections[0], options(uci, "firewall", defaults_sections[0]))
        if defaults_sections
        else None
    )
    base = defaults.values if defaults else {}

    def zone(section: str) -> ZoneConf:
        o = options(uci, "firewall", section)
        # fw4: an unset zone policy is the defaults section's, and DROP when that has none either
        return ZoneConf(
            section=section,
            name=o.get("name", section),
            networks=_items(o.get("network")),
            input=_policy(o.get("input"), base.get("input", "DROP")),
            output=_policy(o.get("output"), base.get("output", "DROP")),
            forward=_policy(o.get("forward"), base.get("forward", "DROP")),
            masq=o.get("masq") == "1",
            mtu_fix=o.get("mtu_fix") == "1",
            others=_others(o, ZONE_FIELDS),
        )

    def forwarding(section: str) -> ForwardingConf:
        o = options(uci, "firewall", section)
        return ForwardingConf(section, o.get("src"), o.get("dest"), _on(o, "enabled"))

    def rule(section: str) -> FwRuleConf:
        o = options(uci, "firewall", section)
        return FwRuleConf(
            section=section,
            name=o.get("name"),
            src=o.get("src"),
            dest=o.get("dest"),
            proto=o.get("proto"),
            src_ip=_items(o.get("src_ip")),
            dest_ip=_items(o.get("dest_ip")),
            src_port=o.get("src_port"),
            dest_port=o.get("dest_port"),
            icmp_type=_items(o.get("icmp_type")),
            family=o.get("family"),
            target=o.get("target", "DROP").upper(),  # fw4's default rule target
            enabled=_on(o, "enabled"),
            others=_others(o, RULE_FIELDS),
        )

    def redirect(section: str) -> RedirectConf:
        o = options(uci, "firewall", section)
        return RedirectConf(
            section=section,
            name=o.get("name"),
            src=o.get("src"),
            src_dport=o.get("src_dport"),
            dest=o.get("dest"),
            dest_ip=o.get("dest_ip"),
            dest_port=o.get("dest_port"),
            proto=o.get("proto"),
            target=o.get("target", "DNAT").upper(),
            enabled=_on(o, "enabled"),
            others=_others(o, REDIRECT_FIELDS),
        )

    def nat(section: str) -> NatConf:
        o = options(uci, "firewall", section)
        return NatConf(
            section=section,
            name=o.get("name"),
            src=o.get("src"),
            src_ip=o.get("src_ip"),
            dest_ip=o.get("dest_ip"),
            dest_port=o.get("dest_port"),
            proto=o.get("proto"),
            target=o.get("target", "SNAT").upper(),
            snat_ip=o.get("snat_ip"),
            snat_port=o.get("snat_port"),
            enabled=_on(o, "enabled"),
            others=_others(o, NAT_FIELDS),
        )

    def ipset(section: str) -> IpsetConf:
        o = options(uci, "firewall", section)
        return IpsetConf(
            section=section,
            name=o.get("name"),
            family=o.get("family", "ipv4"),
            match=_items(o.get("match")),
            entries=_items(o.get("entry")),
            enabled=_on(o, "enabled"),
            others=_others(o, IPSET_FIELDS),
        )

    def include(section: str) -> IncludeConf:
        o = options(uci, "firewall", section)
        return IncludeConf(section, o.get("type"), o.get("path"), o.get("position"))

    def every(type_: str) -> list[str]:
        return sections(uci, "firewall", type_)

    return FirewallConf(
        defaults=defaults,
        zones=tuple(zone(s) for s in every("zone")),
        forwardings=tuple(forwarding(s) for s in every("forwarding")),
        rules=tuple(rule(s) for s in every("rule")),
        redirects=tuple(redirect(s) for s in every("redirect")),
        nats=tuple(nat(s) for s in every("nat")),
        ipsets=tuple(ipset(s) for s in every("ipset")),
        includes=tuple(include(s) for s in every("include")),
    )
