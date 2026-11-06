"""Fault targets (spec 7.7): Wi-Fi stations, host hints, DHCP leases, ARP and the known devices of Settings,
merged by MAC. The panel's Ethernet and Wi-Fi MACs are unrelated, so devices are matched by remembered MAC or
name, never by vendor prefix. The PC and the router itself are never a target."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal

from openwrtgui.faults.model import FaultTarget, TargetRef
from openwrtgui.net.parse import parse_leases
from openwrtgui.net.state import NetworkState
from openwrtgui.ports.parse import parse_arp
from openwrtgui.store.settings import KnownDevice
from openwrtgui.transport.base import Transport, ubus_call
from openwrtgui.wifi.stations import read_stations

_MAC = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")
Needs = Literal["mac", "ip", "both"]


def check_mac(text: str) -> str:
    mac = text.strip().lower().replace("-", ":")
    if not _MAC.fullmatch(mac):
        raise ValueError(f"{text} is not a MAC address")
    return mac


def check_ipv4(text: str) -> str:
    try:
        return str(ipaddress.IPv4Address(text.strip()))
    except ValueError:
        raise ValueError(f"{text} is not an IPv4 address") from None


def lan_wired_device(net: NetworkState) -> str | None:
    """The one wired member of the bridge under lan (`eth0.1` on the DWR-921): Wi-Fi interfaces join the
    bridge at run time and are not in its config."""
    lan = net.conf("lan")
    bridge = next((d for d in net.devices if lan and d.name == lan.device and d.type == "bridge"), None)
    if bridge is None:
        return lan.device if lan and lan.device and not lan.device.startswith("br-") else None
    return bridge.ports[0] if len(bridge.ports) == 1 else None


def _ap_ifaces(status: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for radio in status.values():
        if not isinstance(radio, dict) or not radio.get("up"):
            continue
        for iface in radio.get("interfaces", []):
            if isinstance(iface, dict) and iface.get("ifname"):
                out.append((str(iface["ifname"]), str(iface.get("config", {}).get("ssid", ""))))
    return out


async def read_targets(t: Transport, net: NetworkState, known: Sequence[KnownDevice]) -> list[FaultTarget]:
    ifaces = _ap_ifaces(await ubus_call(t, "network.wireless", "status") or {})
    stations = await read_stations(t, ifaces) if ifaces else []
    hints = await ubus_call(t, "luci-rpc", "getHostHints") or {}
    leases = parse_leases(await ubus_call(t, "luci-rpc", "getDHCPLeases") or {})
    arp = parse_arp((await t.run("cat /proc/net/arp")).stdout)
    seen: dict[str, dict[str, str | None]] = {}

    def entry(mac: str) -> dict[str, str | None]:
        return seen.setdefault(mac.lower(), {"name": None, "ip": None, "via": None})

    for s in stations:
        entry(s.mac)["via"] = s.ifname
    for mac, hint in hints.items():
        if isinstance(hint, dict) and _MAC.fullmatch(mac.lower()):
            e = entry(mac)
            ips = hint.get("ipaddrs") or []
            e["name"] = e["name"] or hint.get("name")
            e["ip"] = e["ip"] or (str(ips[0]) if ips else None)
    for lease in leases:
        if lease.mac and lease.family == 4:
            e = entry(lease.mac)
            e["name"] = e["name"] or lease.hostname
            e["ip"] = e["ip"] or lease.ip
    for ip, mac in arp.items():
        e = entry(mac)
        e["ip"] = e["ip"] or ip
    names = {m.lower(): k.name for k in known for m in k.macs}
    for mac in names:
        entry(mac)
    wired = lan_wired_device(net)
    out = []
    for mac, e in seen.items():
        via = e["via"] or ("wired" if e["ip"] else None)
        device = e["via"] or (wired if via == "wired" else None)
        out.append(FaultTarget(names.get(mac) or e["name"], mac, e["ip"], via, device))
    return sorted(out, key=lambda x: (x.via is None or x.via == "wired", x.name or "~", x.mac or ""))


def resolve(
    ref: TargetRef, targets: Sequence[FaultTarget], net: NetworkState, router_name: str, needs: Needs
) -> FaultTarget:
    """The target a fault asks for, the missing half (MAC or IP) filled from what the router knows."""
    mac = check_mac(ref.mac) if ref.mac else None
    ip = check_ipv4(ref.ip) if ref.ip else None
    if mac is None and ip is None:
        raise ValueError("Pick a target, or enter its IP or MAC")
    found = next((x for x in targets if (mac and x.mac == mac) or (ip and x.ip == ip)), None)
    target = FaultTarget(
        found.name if found else None,
        mac or (found.mac if found else None),
        ip or (found.ip if found else None),
        found.via if found else None,
        found.device if found else None,
    )
    pc_mac = next((x.mac for x in targets if net.pc_ip and x.ip == net.pc_ip), None)
    if (target.ip and target.ip == net.pc_ip) or (target.mac and target.mac == pc_mac):
        raise ValueError(f"{target.ip or net.pc_ip} is this PC (the app's connection to {router_name})")
    mine = {a.ip for v in net.interfaces if v.live for a in v.live.ipv4}
    if target.ip in mine:
        raise ValueError(f"{target.ip} is {router_name} itself")
    if needs in ("mac", "both") and not target.mac:
        raise ValueError(f"No MAC known for {target.ip}; enter one")
    if needs in ("ip", "both") and not target.ip:
        raise ValueError(f"No IPv4 address known for {target.mac}; enter one")
    if target.device is None:
        target = replace(target, device=lan_wired_device(net))
    return target
