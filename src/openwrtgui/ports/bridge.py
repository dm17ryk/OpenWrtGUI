"""DSA bridge VLANs (v1.0a3): what LuCI's Switch/VLAN config page reads (`view/network/switch-vlan.js` and
`tools/bridgevlan.js`), as pure functions, what netifd reports for a bridge's VLANs (`bridge.c`), and the
state the editor shows."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.net.parse import options, sections

Cell = Literal["u", "t"]
MIN_VLAN = 1
MAX_VLAN = 4094
_SPEC = re.compile(r"([^:]+)(?::([ut*]*))?")  # LuCI's parsePortSpec
_VID = re.compile(r"[0-9]{1,4}")
_OFF = frozenset({"0", "false", "no", "off", "disabled"})


@dataclass(frozen=True)
class PortSpec:
    """One `ports` entry as LuCI reads it: a bare name is untagged with PVID."""

    port: str
    tagged: bool
    untagged: bool
    pvid: bool


def parse_spec(text: str) -> PortSpec | None:
    m = _SPEC.fullmatch(text)
    if m is None:
        return None
    flags = m.group(2) or ""
    return PortSpec(m.group(1), "t" in flags, "u" in flags or not flags, "*" in flags or not flags)


def render_spec(port: str, cell: Cell) -> str:
    """LuCI's formatPortSpec: untagged (native) is the bare name, tagged is `name:t`."""
    return f"{port}:t" if cell == "t" else port


def cell_of(spec: PortSpec) -> Cell:
    return "t" if spec.tagged else "u"


def netifd_spec(text: str) -> str | None:
    """The entry as netifd prints it in `network.device status` (bridge.c, bridge_dump_port). Its config
    parser knows `t` and `*` only, so a bare name and `:u` both print `name`, and `:*` and `:u*` both print
    `name:*`."""
    m = _SPEC.fullmatch(text)
    if m is None:
        return None
    flags = m.group(2) or ""
    tagged, star = "t" in flags, "*" in flags
    return f"{m.group(1)}{':' if tagged or star else ''}{'t' if tagged else ''}{'*' if star else ''}"


def natural(name: str) -> tuple[str | int, ...]:
    """LuCI's naturalCompare order: lan2 before lan10. Digit runs sit at odd positions, so types line up."""
    return tuple(int(part) if i % 2 else part for i, part in enumerate(re.split(r"(\d+)", name)))


def parse_local(value: str | None) -> bool:
    """LuCI's parseLocal: absent is on, which is netifd's default."""
    return not value or value.strip().lower() not in _OFF


@dataclass(frozen=True)
class BridgeDevice:
    section: str
    name: str
    ports: tuple[str, ...]
    vlan_filtering: bool


@dataclass(frozen=True)
class BridgeVlanConf:
    section: str
    device: str
    vlan: int | None  # None: not a VLAN number from 1 to 4094
    raw_vlan: str
    local: bool
    entries: tuple[str, ...]  # `ports` as written


def bridge_devices(uci: Mapping[str, str]) -> list[BridgeDevice]:
    out = []
    for section in sections(uci, "network", "device"):
        o = options(uci, "network", section)
        if o.get("type") == "bridge":
            ports = tuple(o.get("ports", "").split())
            out.append(BridgeDevice(section, o.get("name", ""), ports, o.get("vlan_filtering") == "1"))
    return out


def _vid(raw: str) -> int | None:
    return int(raw) if _VID.fullmatch(raw) and MIN_VLAN <= int(raw) <= MAX_VLAN else None


def bridge_vlans(uci: Mapping[str, str]) -> list[BridgeVlanConf]:
    out = []
    for section in sections(uci, "network", "bridge-vlan"):
        o = options(uci, "network", section)
        raw = o.get("vlan", "")
        entries = tuple(o.get("ports", "").split())
        local = parse_local(o.get("local"))
        out.append(BridgeVlanConf(section, o.get("device", ""), _vid(raw), raw, local, entries))
    return out


def members(device: BridgeDevice, vlans: Sequence[BridgeVlanConf]) -> tuple[str, ...]:
    """The bridge's configured ports and every port its bridge-vlans name (netifd adds those as members)."""
    named = {p.port for v in vlans if v.device == device.name for p in map(parse_spec, v.entries) if p}
    return tuple(sorted({*device.ports, *named}, key=natural))


def _filtering(device: BridgeDevice, vlans: Sequence[BridgeVlanConf]) -> bool:
    """LuCI's isVlanFilteringEnabled: vlan_filtering='1', or a bridge-vlan names the bridge."""
    return device.vlan_filtering or any(v.device == device.name for v in vlans)


def find_active_bridge(
    devices: Sequence[BridgeDevice], vlans: Sequence[BridgeVlanConf], physical: frozenset[str]
) -> BridgeDevice | None:
    """LuCI's findActiveBridge: the first bridge with VLAN filtering whose members are all the router's own
    ports. Members Wi-Fi adds at run time are not counted (D2 d)."""
    for device in devices:
        ports = members(device, vlans)
        if _filtering(device, vlans) and ports and all(p in physical for p in ports):
            return device
    return None


def _entry_issue(vlan: int, text: str, spec: PortSpec | None) -> str | None:
    if spec is None:
        return f"VLAN {vlan}: {text!r} is not a port entry"
    if spec.tagged and spec.pvid:
        return f"VLAN {vlan}: {spec.port} is tagged and PVID at once ({text})"
    if spec.tagged and spec.untagged:
        return f"VLAN {vlan}: {spec.port} is tagged and untagged at once ({text})"
    if not spec.tagged and not spec.untagged:
        return f"VLAN {vlan}: {spec.port} has a PVID but no traffic ({text})"
    return None


def unsupported(bridge: str, vlans: Sequence[BridgeVlanConf]) -> list[str]:
    """LuCI's checkUnsupportedConfig, plus a VLAN configured twice (D2 e): any one keeps the card read
    only."""
    issues: list[str] = []
    untagged: dict[str, int] = {}
    seen: set[int] = set()
    for v in (v for v in vlans if v.device == bridge):
        if v.vlan is None:
            issues.append(f"VLAN {v.raw_vlan!r} is not a VLAN number from {MIN_VLAN} to {MAX_VLAN}")
            continue
        if v.vlan in seen:
            issues.append(f"VLAN {v.vlan} is configured twice")
        seen.add(v.vlan)
        for text in v.entries:
            spec = parse_spec(text)
            issue = _entry_issue(v.vlan, text, spec)
            if issue is not None:
                issues.append(issue)
            elif spec is not None and spec.untagged:
                if spec.port in untagged:
                    issues.append(f"{spec.port} is untagged in VLAN {untagged[spec.port]} and VLAN {v.vlan}")
                else:
                    untagged[spec.port] = v.vlan
    return issues


@dataclass(frozen=True)
class LiveVlan:
    """One VLAN as netifd reports it: the verify compares these with what the change asks (D4)."""

    vlan: int
    local: bool
    ports: frozenset[str]  # netifd's entries (`lan1`, `lan1:t`, `lan1:*`), own ports only


def _port_name(entry: str) -> str:
    return entry.split(":", 1)[0]


def live_vlans(status_json: str, bridge: str, ports: frozenset[str]) -> tuple[LiveVlan, ...]:
    """`ubus call network.device status`: the bridge's `bridge-vlans`, counting the editor's own ports
    only."""
    try:
        status = json.loads(status_json)
    except ValueError:
        return ()
    entry = status.get(bridge) if isinstance(status, dict) else None
    listed = entry.get("bridge-vlans") if isinstance(entry, dict) else None
    if not isinstance(listed, list):
        return ()
    out = []
    for v in listed:
        if isinstance(v, dict) and isinstance(v.get("id"), int):
            entries = [p for p in v.get("ports", []) if isinstance(p, str) and _port_name(p) in ports]
            out.append(LiveVlan(v["id"], bool(v.get("local", True)), frozenset(entries)))
    return tuple(sorted(out, key=lambda x: x.vlan))


@dataclass(frozen=True)
class BridgePortView:
    name: str
    link: bool | None  # None: netifd reports no carrier for the port
    may_carry: bool  # D3: a member of the app's own VLAN with a link, or with no link state (fail closed)


@dataclass(frozen=True)
class BridgeVlanView:
    section: str
    vlan: int
    local: bool
    members: dict[str, Cell]
    entries: dict[str, str]  # port -> its entry as written; an unchanged cell keeps it (D2 a)
    used_by: tuple[str, ...]  # interfaces on <bridge>.<vid>, directly or through a bridge
    own: bool  # carries the app's interface


@dataclass(frozen=True)
class BridgeState:
    router_id: str
    bridge: str | None  # None: no VLAN-filtering bridge of the router's own ports
    editable: bool
    blocker: str | None  # why the card is read only, or why there is no bridge to show
    issues: tuple[str, ...]  # LuCI's unsupported-config issues
    ports: tuple[BridgePortView, ...]
    vlans: tuple[BridgeVlanView, ...]
    own_interface: str | None
    own_vlan: int | None
    runtime: tuple[str, ...] = ()  # members Wi-Fi joins at run time: listed, never edited (D2 d)
