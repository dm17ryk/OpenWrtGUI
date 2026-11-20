"""The SIP ALG switch per zone (v1.2b R7): fw4's uci, by what its ruleset shows."""

from __future__ import annotations

import pytest

from openwrtgui.fw.sip import (
    NO_FW4,
    SipAlgRequest,
    SipZone,
    compile_sip_alg,
    sip_alg_zones,
    sip_ops,
)
from openwrtgui.system.parse import available_helpers, zone_helpers
from openwrtgui.uci import UciOp

TEN = ["amanda", "RAS", "Q.931", "irc", "netbios-ns", "pptp", "sane", "sip", "snmp", "tftp"]
NINE = [h for h in TEN if h != "sip"]
LAN = "firewall.cfg02dc81"
UCI = {LAN: "zone", f"{LAN}.name": "lan", "firewall.cfg03dc81": "zone", "firewall.cfg03dc81.name": "wan"}
UCI["firewall.cfg03dc81.masq"] = "1"


def _ruleset(chains: dict[str, list[str]], helpers: list[str] = TEN) -> str:
    lines = ["table inet fw4 { # handle 1"]
    for i, name in enumerate(helpers):
        lines += [f"\tct helper {name} {{ # handle {30 + i}", '\t\ttype "x" protocol udp', "\t}"]
    for zone, names in chains.items():
        lines.append(f"\tchain helper_{zone} {{ # handle 10")
        lines += [f'\t\tudp dport 1 ct helper set "{n}" comment "!fw4: {n}" # handle 1' for n in names]
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def test_available_and_zone_helpers() -> None:
    text = _ruleset({"lan": TEN, "guest": ["tftp"]})
    assert available_helpers(text) == TEN
    assert zone_helpers(text) == {"lan": TEN, "guest": ["tftp"]}
    assert available_helpers("table inet other {\n\tct helper sip { # handle 1\n\t}\n}\n") == []


def test_off_from_fw4s_default() -> None:
    zone = SipZone(zone="lan", section="cfg02dc81", sip=True, helpers=TEN)
    assert compile_sip_alg(UCI, zone, False, TEN) == [
        UciOp("set", f"{LAN}.auto_helper", "0"),
        *[UciOp("add_list", f"{LAN}.helper", h) for h in NINE],
    ]


def test_on_back_to_fw4s_default() -> None:
    uci = {**UCI, f"{LAN}.auto_helper": "0", f"{LAN}.helper": " ".join(NINE)}
    zone = SipZone(zone="lan", section="cfg02dc81", sip=False, helpers=NINE)
    assert compile_sip_alg(uci, zone, True, TEN) == [
        UciOp("delete", f"{LAN}.helper"),
        UciOp("delete", f"{LAN}.auto_helper"),
    ]


def test_off_from_an_explicit_list() -> None:
    uci = {**UCI, f"{LAN}.helper": "sip tftp"}
    zone = SipZone(zone="lan", section="cfg02dc81", sip=True, helpers=["sip", "tftp"])
    assert compile_sip_alg(uci, zone, False, TEN) == [UciOp("del_list", f"{LAN}.helper", "sip")]


def test_on_with_a_users_own_list() -> None:
    uci = {**UCI, f"{LAN}.auto_helper": "0", f"{LAN}.helper": "irc tftp"}
    zone = SipZone(zone="lan", section="cfg02dc81", sip=False, helpers=["irc", "tftp"])
    assert compile_sip_alg(uci, zone, True, TEN) == [UciOp("add_list", f"{LAN}.helper", "sip")]


def test_already_on_or_off() -> None:
    zone = SipZone(zone="lan", section="cfg02dc81", sip=True, helpers=TEN)
    with pytest.raises(ValueError, match=r"^SIP ALG is already on in zone lan\.$"):
        compile_sip_alg(UCI, zone, True, TEN)
    off = zone.model_copy(update={"sip": False})
    with pytest.raises(ValueError, match=r"^SIP ALG is already off in zone lan\.$"):
        compile_sip_alg(UCI, off, False, TEN)


def test_the_zones_listed() -> None:
    zones = sip_alg_zones(UCI, _ruleset({"lan": TEN}))
    assert zones.state == "on" and zones.available == TEN
    assert zones.zones == [SipZone(zone="lan", section="cfg02dc81", sip=True, helpers=TEN)]
    uci = {**UCI, f"{LAN}.auto_helper": "0", f"{LAN}.helper": " ".join(NINE)}
    off = sip_alg_zones(uci, _ruleset({"lan": NINE}))
    assert off.state == "off" and off.zones[0].sip is False
    bare = {**UCI, f"{LAN}.auto_helper": "0"}  # no chain, but auto_helper '0': listed, to switch on
    assert [z.zone for z in sip_alg_zones(bare, _ruleset({})).zones] == ["lan"]


def test_a_masquerading_zone_has_nothing_to_switch() -> None:
    with pytest.raises(
        ValueError, match=r"^Zone wan runs no conntrack helpers, so it has no SIP ALG to switch\.$"
    ):
        sip_ops(UCI, _ruleset({"lan": TEN}), SipAlgRequest(zone="wan", on=False))


def test_no_fw4() -> None:
    assert sip_alg_zones(UCI, "table inet other {\n}\n").state == "unknown"
    with pytest.raises(ValueError, match=f"^{NO_FW4}$"):
        sip_ops(UCI, "table inet other {\n}\n", SipAlgRequest(zone="lan", on=False))
    assert NO_FW4 == "This router has no fw4 ruleset, so SIP ALG cannot be switched here."


def test_ops_for_a_zone() -> None:
    zone, ops = sip_ops(UCI, _ruleset({"lan": TEN}), SipAlgRequest(zone="lan", on=False))
    assert zone.section == "cfg02dc81" and ops[0] == UciOp("set", f"{LAN}.auto_helper", "0")
