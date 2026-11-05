"""Wi-Fi access by MAC (spec 7.4): Everyone / Block listed / Only listed per SSID, and three ways to block one
device: now with no Wi-Fi restart (`hostapd_cli … deny_acl`), for N s (`del_client` with `ban_time`), or saved
(uci `macfilter` / `maclist`, applied through the Wi-Fi screen's apply). The runtime lists last until the
next Wi-Fi restart (O8 still open)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from openwrtgui.transport.base import Transport
from openwrtgui.uci import UciOp
from openwrtgui.wifi.service import BLOCK_MAX_S, BLOCK_MIN_S
from openwrtgui.wifi.stations import del_client_command

Policy = Literal["everyone", "deny", "allow"]
Kind = Literal["policy", "block", "unblock"]
Method = Literal["now", "timed", "saved"]
POLICY_LABEL: dict[str, str] = {"everyone": "Everyone", "deny": "Block listed", "allow": "Only listed"}
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@dataclass(frozen=True)
class SsidAccess:
    section: str
    ssid: str
    radio: str
    ifname: str | None  # None: not on air
    policy: Policy
    maclist: tuple[str, ...]
    runtime: tuple[str, ...]  # hostapd's runtime list: deny_acl, or accept_acl for Only listed


@dataclass(frozen=True)
class AccessDevice:
    mac: str
    name: str | None
    saved_in: tuple[str, ...]  # SSID sections whose saved list has it
    blocked_now_on: tuple[str, ...]  # AP interfaces whose runtime deny list has it


@dataclass(frozen=True)
class AccessState:
    ssids: tuple[SsidAccess, ...]
    devices: tuple[AccessDevice, ...]


@dataclass(frozen=True)
class AccessChange:
    kind: Kind
    sections: tuple[str, ...]
    policy: Policy | None = None
    mac: str | None = None
    method: Method | None = None
    seconds: int | None = None


def policy_of(uci: Mapping[str, str], section: str) -> Policy:
    value = uci.get(f"wireless.{section}.macfilter", "")
    return "deny" if value == "deny" else "allow" if value == "allow" else "everyone"


def acl_list(policy: Policy) -> str:
    return "accept_acl" if policy == "allow" else "deny_acl"


def acl_show(ifname: str, policy: Policy) -> str:
    return f"hostapd_cli -i {ifname} {acl_list(policy)} SHOW"


def _macs(text: str) -> tuple[str, ...]:
    return tuple(
        line.split()[0].lower()
        for line in text.splitlines()
        if line.split() and _MAC.match(line.split()[0].lower())
    )


async def read_access(
    t: Transport, uci: Mapping[str, str], status: Mapping[str, Any], hints: Mapping[str, str]
) -> AccessState:
    up = {
        str(i.get("section")): str(i["ifname"])
        for radio in status.values()
        if isinstance(radio, dict) and radio.get("up")
        for i in radio.get("interfaces", [])
        if i.get("ifname")
    }
    ssids = []
    for key, value in uci.items():
        if key.count(".") != 1 or value != "wifi-iface":
            continue
        section = key.split(".")[1]
        policy = policy_of(uci, section)
        ifname = up.get(section)
        runtime: tuple[str, ...] = ()
        if ifname:
            shown = await t.run(acl_show(ifname, policy))
            runtime = _macs(shown.stdout) if shown.ok else ()
        ssids.append(
            SsidAccess(
                section=section,
                ssid=uci.get(f"wireless.{section}.ssid", section),
                radio=uci.get(f"wireless.{section}.device", ""),
                ifname=ifname,
                policy=policy,
                maclist=tuple(m.lower() for m in uci.get(f"wireless.{section}.maclist", "").split()),
                runtime=runtime,
            )
        )
    macs = dict.fromkeys([m for s in ssids for m in (*s.maclist, *s.runtime)])
    devices = tuple(
        AccessDevice(
            mac=mac,
            name=hints.get(mac),
            saved_in=tuple(s.section for s in ssids if mac in s.maclist),
            blocked_now_on=tuple(
                s.ifname for s in ssids if s.ifname and s.policy != "allow" and mac in s.runtime
            ),
        )
        for mac in macs
    )
    return AccessState(tuple(ssids), devices)


def _mac(text: str | None) -> str:
    mac = (text or "").strip().lower().replace("-", ":")
    if not _MAC.match(mac):
        raise ValueError(f"{text} is not a MAC address")
    return mac


def _targets(change: AccessChange, state: AccessState, router_name: str) -> list[SsidAccess]:
    by_section = {s.section: s for s in state.ssids}
    if not change.sections:
        raise ValueError("Tick at least one SSID")
    for section in change.sections:
        if section not in by_section:
            raise ValueError(f"{section} is not an SSID of {router_name}")
    return [by_section[s] for s in change.sections]


def _policy_ops(change: AccessChange, ssids: Sequence[SsidAccess]) -> list[UciOp]:
    ops: list[UciOp] = []
    for s in ssids:
        path = f"wireless.{s.section}.macfilter"
        if change.policy == "allow" and not s.maclist:
            raise ValueError(
                "Add a device to the list before choosing Only listed: "
                f"an empty list keeps every device off {s.ssid}."
            )
        ops.append(
            UciOp("delete", path) if change.policy == "everyone" else UciOp("set", path, str(change.policy))
        )
    return ops


def _saved_ops(change: AccessChange, s: SsidAccess, mac: str, warnings: list[str]) -> list[UciOp]:
    p = f"wireless.{s.section}"
    block = change.kind == "block"
    if s.policy == "everyone":
        if not block:
            return []
        warnings.append(f"{s.ssid} changes from Everyone to Block listed.")
        return [UciOp("set", f"{p}.macfilter", "deny"), UciOp("add_list", f"{p}.maclist", mac)]
    listed = mac in s.maclist
    add = block == (s.policy == "deny")  # block on a deny list, or unblock on an allow list, adds it
    if add and not listed:
        return [UciOp("add_list", f"{p}.maclist", mac)]
    if not add and listed:
        return [UciOp("del_list", f"{p}.maclist", mac)]
    return []


def _runtime_commands(change: AccessChange, s: SsidAccess, mac: str) -> list[str]:
    method = change.method
    if s.ifname is None:
        if method == "now":
            raise ValueError(f"{s.ssid} is not on air; a block now needs the radio up. Use For N s or Saved.")
        raise ValueError(f"{s.ssid} is not on air; a block for N s needs the radio up. Use Saved.")
    if method == "timed":
        if change.kind != "block":
            raise ValueError("A block for N s ends by itself")
        seconds = change.seconds or 0
        if not BLOCK_MIN_S <= seconds <= BLOCK_MAX_S:
            raise ValueError(f"Block for {BLOCK_MIN_S} to {BLOCK_MAX_S} seconds")
        return [del_client_command(s.ifname, mac, seconds * 1000)]
    block = change.kind == "block"
    if s.policy == "allow":  # Only listed: blocking takes the device off the accept list, then kicks it
        verb = "DEL_MAC" if block else "ADD_MAC"
        commands = [f"hostapd_cli -i {s.ifname} accept_acl {verb} {mac}"]
        return commands + ([del_client_command(s.ifname, mac, 0)] if block else [])
    return [f"hostapd_cli -i {s.ifname} deny_acl {'ADD_MAC' if block else 'DEL_MAC'} {mac}"]


def compile_access(
    change: AccessChange, state: AccessState, router_name: str
) -> tuple[list[UciOp], list[str], list[str]]:
    """Wireless uci operations, runtime commands and warnings for one access change."""
    ssids = _targets(change, state, router_name)
    if change.kind == "policy":
        if change.policy is None:
            raise ValueError("Choose Everyone, Block listed or Only listed")
        return _policy_ops(change, ssids), [], []
    mac = _mac(change.mac)
    ops: list[UciOp] = []
    commands: list[str] = []
    warnings: list[str] = []
    for s in ssids:
        if change.method == "saved":
            ops += _saved_ops(change, s, mac, warnings)
        else:
            commands += _runtime_commands(change, s, mac)
    return ops, commands, warnings
