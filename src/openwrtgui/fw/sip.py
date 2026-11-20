"""The SIP ALG switch per zone (v1.2b R7), from fw4's uci and its ruleset.

Available helpers are the `ct helper <name>` objects fw4 declares; a zone's helpers are the rules in its
`chain helper_<zone>`. Off: a zone with an explicit `list helper` loses `sip`; otherwise it gets
`auto_helper '0'` plus its other helpers as a list, in ruleset order. On: a zone whose `auto_helper '0'` list
is exactly the available helpers minus `sip` gets both options deleted, back to fw4's default, which is what
Off replaced; any other zone gets `sip` added to its list."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.system.parse import available_helpers, parse_sip_alg, zone_helpers
from openwrtgui.uci import UciOp

SIP = "sip"
NO_FW4 = "This router has no fw4 ruleset, so SIP ALG cannot be switched here."
CONNECTIONS_WARNING = "Connections set up before the change keep their helper until they end."


def no_helpers(zone: str) -> str:
    return f"Zone {zone} runs no conntrack helpers, so it has no SIP ALG to switch."


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class SipZone(_Frozen):
    zone: str
    section: str
    sip: bool
    helpers: list[str]


class SipAlgZones(_Frozen):
    state: Literal["on", "off", "unknown"]
    available: list[str]
    zones: list[SipZone]


class SipAlgRequest(BaseModel):
    zone: str
    on: bool


class SipAlgApply(SipAlgRequest):
    digest: str


def _zone_sections(uci: Mapping[str, str]) -> list[tuple[str, str]]:
    """(name, section) of each firewall zone, in the config's order."""
    out = []
    for key, value in uci.items():
        parts = key.split(".")
        if len(parts) == 2 and parts[0] == "firewall" and value == "zone":
            out.append((uci.get(f"{key}.name", parts[1]), parts[1]))
    return out


def sip_alg_zones(uci: Mapping[str, str], nft_text: str) -> SipAlgZones:
    """The zones that run helpers, or whose helpers the config sets (a helper chain, `auto_helper '0'` or a
    `helper` list)."""
    state = parse_sip_alg(nft_text).state
    if state == "unknown":
        return SipAlgZones(state="unknown", available=[], zones=[])
    chains = zone_helpers(nft_text)
    zones = []
    for name, section in _zone_sections(uci):
        path = f"firewall.{section}"
        if name in chains or uci.get(f"{path}.auto_helper") == "0" or uci.get(f"{path}.helper"):
            helpers = chains.get(name, [])
            zones.append(SipZone(zone=name, section=section, sip=SIP in helpers, helpers=helpers))
    return SipAlgZones(state=state, available=available_helpers(nft_text), zones=zones)


def compile_sip_alg(uci: Mapping[str, str], zone: SipZone, on: bool, available: Sequence[str]) -> list[UciOp]:
    if zone.sip == on:
        raise ValueError(f"SIP ALG is already {'on' if on else 'off'} in zone {zone.zone}.")
    path = f"firewall.{zone.section}"
    listed = uci.get(f"{path}.helper", "").split()
    if not on:
        if listed:
            return [UciOp("del_list", f"{path}.helper", SIP)]
        others = [h for h in zone.helpers if h != SIP]
        return [
            UciOp("set", f"{path}.auto_helper", "0"),
            *[UciOp("add_list", f"{path}.helper", h) for h in others],
        ]
    default_off = [h for h in available if h != SIP]
    if uci.get(f"{path}.auto_helper") == "0" and sorted(listed) == sorted(default_off):
        return [UciOp("delete", f"{path}.helper"), UciOp("delete", f"{path}.auto_helper")]
    return [UciOp("add_list", f"{path}.helper", SIP)]


def sip_ops(uci: Mapping[str, str], nft_text: str, req: SipAlgRequest) -> tuple[SipZone, list[UciOp]]:
    zones = sip_alg_zones(uci, nft_text)
    if zones.state == "unknown":
        raise ValueError(NO_FW4)
    zone = next((z for z in zones.zones if z.zone == req.zone), None)
    if zone is None:
        raise ValueError(no_helpers(req.zone))
    return zone, compile_sip_alg(uci, zone, req.on, zones.available)
