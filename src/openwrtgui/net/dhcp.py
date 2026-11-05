"""DHCP server per interface and fixed addresses by MAC (spec 7.4), as `dhcp` uci changes.

`dhcp` changes are plain applies: `uci commit dhcp` and a dnsmasq reload (odhcpd too for IPv6 options).
Before a server is turned on, the other known routers on the same subnet are checked (spec 6).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.net.model import Address
from openwrtgui.net.state import NetworkState
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.uci import UciOp

V6Mode = Literal["server", "relay", "hybrid", "disabled"]
V6_MODES = ("server", "relay", "hybrid", "disabled")
V6_OPTIONS = frozenset({"ra", "dhcpv6", "ndp", "ra_flags", "ra_slaac", "ra_management"})
DNSMASQ_RELOAD = "/etc/init.d/dnsmasq reload"
ODHCPD_RELOAD = "/etc/init.d/odhcpd reload"
_LEASE = re.compile(r"^(\d+[smhdw]?|infinite)$")
_OPTION = re.compile(r"^(\d{1,3}),(.+)$")
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_NAME = re.compile(r"^[A-Za-z0-9-]{1,63}$")
LEASE_REFUSAL = "Lease time is a number with s, m, h, d or w (e.g. 12h), or infinite"


@dataclass(frozen=True)
class DhcpRequest:
    interface: str
    enabled: bool | None = None
    start: int | None = None
    limit: int | None = None
    leasetime: str | None = None
    options: tuple[str, ...] | None = None
    dhcpv6: V6Mode | None = None
    ra: V6Mode | None = None


@dataclass(frozen=True)
class HostRequest:
    section: str | None  # None: a new fixed address
    mac: str
    name: str | None = None
    ip: str | None = None
    leasetime: str | None = None
    gets_address: bool = True


def _leasetime(value: str) -> str:
    if not _LEASE.match(value):
        raise ValueError(LEASE_REFUSAL)
    return value


def _pool(start: int, limit: int, address: Address | None) -> None:
    if address is None:
        return
    network = ipaddress.ip_interface(str(address)).network
    hosts = network.num_addresses - 2
    if start < 1 or limit < 1 or start + limit - 1 > hosts:
        raise ValueError(f"The pool {start} to {start + limit - 1} does not fit in {network}")


def compile_dhcp(req: DhcpRequest, state: NetworkState, uci: Mapping[str, str]) -> list[UciOp]:
    conf = state.conf(req.interface)
    if conf is None:
        raise ValueError(f"There is no interface named {req.interface}")
    current = next((d for d in state.dhcp if d.interface == req.interface), None)
    section = current.section if current else req.interface
    p = f"dhcp.{section}"
    ops: list[UciOp] = []
    if current is None:
        ops += [UciOp("set", p, "dhcp"), UciOp("set", f"{p}.interface", req.interface)]
    if req.start is not None or req.limit is not None:
        start = req.start if req.start is not None else (current.start if current and current.start else 100)
        limit = req.limit if req.limit is not None else (current.limit if current and current.limit else 150)
        _pool(start, limit, conf.address)
        if req.start is not None:
            ops.append(UciOp("set", f"{p}.start", str(req.start)))
        if req.limit is not None:
            ops.append(UciOp("set", f"{p}.limit", str(req.limit)))
    if req.leasetime is not None:
        ops.append(UciOp("set", f"{p}.leasetime", _leasetime(req.leasetime)))
    if req.options is not None:
        for option in req.options:
            m = _OPTION.match(option.strip())
            if not m or not 1 <= int(m.group(1)) <= 254:
                raise ValueError("DHCP option codes are 1 to 254")
        ops += [
            UciOp("delete", f"{p}.dhcp_option"),
            *(UciOp("add_list", f"{p}.dhcp_option", o) for o in req.options),
        ]
    for name, mode in (("dhcpv6", req.dhcpv6), ("ra", req.ra)):
        if mode is not None:
            if mode not in V6_MODES:
                raise ValueError(f"{name} is server, relay, hybrid or disabled")
            ops.append(UciOp("set", f"{p}.{name}", mode))
    if req.enabled is not None:
        ops.append(UciOp("delete", f"{p}.ignore") if req.enabled else UciOp("set", f"{p}.ignore", "1"))
    return ops


def reloads_for(ops: Sequence[UciOp]) -> tuple[str, ...]:
    v6 = any(op.path.rsplit(".", 1)[-1] in V6_OPTIONS for op in ops)
    return (DNSMASQ_RELOAD, ODHCPD_RELOAD) if v6 else (DNSMASQ_RELOAD,)


def _overlaps(addresses: Sequence[str], network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    for text in addresses:
        try:
            if ipaddress.ip_interface(text).network.overlaps(network):
                return True
        except ValueError:
            continue
    return False


def conflict_warnings(
    rec: RouterRecord, subnet: Address, statuses: Mapping[str, RouterStatus], routers: RouterStore
) -> list[str]:
    """Other known routers that already serve DHCP on this subnet (spec 6, "DHCP conflict")."""
    network = ipaddress.ip_interface(str(subnet)).network
    out: list[str] = []
    for other in routers.list():
        if other.id == rec.id:
            continue
        status = statuses.get(other.id)
        if status is None or status.dhcp_server_on is None:
            out.append(f"Could not check {other.name}: no status yet.")
        elif status.dhcp_server_on and _overlaps([a for i in status.interfaces for a in i.ipv4], network):
            out.append(
                f"{other.name} already serves DHCP on {network}. Two DHCP servers on one subnet hand out "
                f"clashing addresses; on the bench, AP1 is the only DHCP server."
            )
    return out


def _mac(text: str) -> str:
    mac = text.strip().lower().replace("-", ":")
    if not _MAC.match(mac):
        raise ValueError(f"{text} is not a MAC address")
    return mac


def _ipv4(text: str) -> str:
    try:
        return str(ipaddress.IPv4Address(text.strip()))
    except ValueError:
        raise ValueError(f"{text} is not an IPv4 address") from None


def _label(name: str | None, ip: str | None, section: str) -> str:
    return name or ip or section


def compile_hosts(
    upserts: Sequence[HostRequest],
    deletes: Sequence[str],
    state: NetworkState,
    uci: Mapping[str, str],
    router_name: str,
) -> tuple[list[UciOp], list[str]]:
    """uci operations and warnings for added, edited and deleted fixed addresses."""
    known = {h.section: h for h in state.hosts}
    for section in deletes:
        if section not in known:
            raise ValueError(f"There is no fixed address {section}")
    edited = {u.section for u in upserts if u.section}
    others = [h for h in state.hosts if h.section not in set(deletes) | edited]
    taken_macs = {m: _label(h.name, h.ip, h.section) for h in others for m in h.macs}
    taken_ips = {h.ip: _label(h.name, None, h.section) for h in others if h.ip}
    subnets = [
        ipaddress.ip_interface(str(i.address)).network
        for i in (v.conf for v in state.interfaces)
        if i and i.address
    ]
    ops: list[UciOp] = []
    warnings: list[str] = []
    new = 0
    for req in upserts:
        mac = _mac(req.mac)
        ip = _ipv4(req.ip) if req.ip else None
        if req.name is not None and req.name and not _NAME.match(req.name):
            raise ValueError("A name is letters, digits and -, up to 63")
        if mac in taken_macs:
            raise ValueError(f"{mac} already has a fixed address ({taken_macs[mac]})")
        if ip is not None and ip in taken_ips:
            raise ValueError(f"{ip} is already fixed for {taken_ips[ip]}")
        if ip is not None and not any(ipaddress.ip_address(ip) in n for n in subnets):
            warnings.append(f"{ip} is outside every subnet of {router_name}")
        taken_macs[mac] = _label(req.name, ip, req.section or "")
        if ip:
            taken_ips[ip] = _label(req.name, ip, req.section or "")
        if req.section is None:
            new += 1
            p = f"dhcp.$h{new}"
            ops.append(UciOp("add", p, "host"))
            ops += [
                UciOp("set", f"{p}.{k}", v) for k, v in (("name", req.name), ("mac", mac), ("ip", ip)) if v
            ]
            if req.leasetime:
                ops.append(UciOp("set", f"{p}.leasetime", _leasetime(req.leasetime)))
            if not req.gets_address:
                ops.append(UciOp("set", f"{p}.ignore", "1"))
            continue
        if req.section not in known:
            raise ValueError(f"There is no fixed address {req.section}")
        p = f"dhcp.{req.section}"
        for key, value in (("name", req.name or None), ("mac", mac), ("ip", ip)):
            ops.append(UciOp("set", f"{p}.{key}", value) if value else UciOp("delete", f"{p}.{key}"))
        lease = _leasetime(req.leasetime) if req.leasetime else None
        ops.append(UciOp("set", f"{p}.leasetime", lease) if lease else UciOp("delete", f"{p}.leasetime"))
        ops.append(UciOp("delete", f"{p}.ignore") if req.gets_address else UciOp("set", f"{p}.ignore", "1"))
    ops += [UciOp("delete", f"dhcp.{section}") for section in deletes]
    return ops, warnings
