"""Router addresses (spec 7.4): every interface as Static / DHCP client / No address / LTE / PPP, with the
common fields laid out by hand and the rest from the router's protocol handlers (All options)."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from openwrtgui import forms
from openwrtgui.forms import OptionEdit, OptionRow
from openwrtgui.net.model import Address, parse_cidr
from openwrtgui.net.parse import options
from openwrtgui.net.state import NetworkState, proto_label
from openwrtgui.store.routers import RouterRecord
from openwrtgui.uci import UciOp

CONTROLLED_INTERFACE = {
    "proto": "Protocol",
    "device": "Device",
    "ipaddr": "Address",
    "netmask": "Address (prefix)",
    "gateway": "Gateway",
    "dns": "DNS servers",
    "mtu": "MTU",
}
STATIC_ONLY = ("ipaddr", "netmask", "gateway", "broadcast")
_NAME = re.compile(r"^[A-Za-z0-9_]{1,15}$")
MTU_MIN, MTU_MAX = 68, 9000


@dataclass(frozen=True)
class InterfaceRequest:
    name: str
    create: bool = False
    delete: bool = False
    proto: str | None = None
    device: str | None = None
    address: str | None = None
    gateway: str | None = None  # "" removes it
    dns: tuple[str, ...] | None = None
    mtu: int | None = None
    bridge_ports: tuple[str, ...] | None = None
    edits: tuple[OptionEdit, ...] = field(default=(), repr=False)


def interface_rows(
    state: NetworkState, uci: Mapping[str, str], handlers: Mapping[str, Mapping[str, str]], name: str
) -> list[OptionRow]:
    conf = state.conf(name)
    if conf is None:
        raise ValueError(f"There is no interface named {name}")
    return forms.option_rows(
        "network",
        [("interface", name)],
        {"interface": handlers.get(conf.proto, {})},
        uci,
        controlled={"interface": CONTROLLED_INTERFACE},
    )


def check_name(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError("An interface name is 1 to 15 letters, digits or _")


def check_proto(proto: str, handlers: Mapping[str, Mapping[str, str]], router_name: str) -> None:
    """A protocol the router has no handler for would be written and never come up (#31)."""
    have = sorted({*handlers, "none"})
    if proto not in have:
        raise ValueError(f"{router_name} has no handler for protocol '{proto}'. It has: {', '.join(have)}.")


def _ipv4(text: str) -> str:
    try:
        return str(ipaddress.IPv4Address(text.strip()))
    except ValueError:
        raise ValueError(f"{text} is not an IPv4 address") from None


def _ip(text: str) -> str:
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        raise ValueError(f"{text} is not an IP address") from None


def _refuse_own(req: InterfaceRequest, state: NetworkState, router_name: str) -> None:
    if req.name != state.own_interface:
        return
    if req.delete:
        raise ValueError(
            f"{req.name} carries this app's connection to {router_name}; it cannot be deleted here."
        )
    if req.proto is not None and req.proto != "static":
        raise ValueError(
            f"{req.name} carries this app's connection to {router_name}; with {proto_label(req.proto)} "
            "the app has no known address to reconnect to."
        )


def _existing(req: InterfaceRequest, state: NetworkState) -> None:
    dynamic = state.dynamic(req.name)
    if dynamic is not None:
        parent = dynamic.dynamic_parent or "its parent"
        raise ValueError(f"{req.name} is made by {parent} at run time; change {parent} instead.")
    if req.create:
        check_name(req.name)
        if state.conf(req.name) is not None:
            raise ValueError(f"There is already an interface named {req.name}")
    elif state.conf(req.name) is None:
        raise ValueError(f"There is no interface named {req.name}")


def _proto_ops(
    req: InterfaceRequest,
    current: str,
    set_here: Mapping[str, str],
    handlers: Mapping[str, Mapping[str, str]],
    router_name: str,
) -> list[UciOp]:
    if req.proto is None or req.proto == current:
        return []
    check_proto(req.proto, handlers, router_name)
    p = f"network.{req.name}"
    ops = [UciOp("set", f"{p}.proto", req.proto)]
    gone = set(handlers.get(current, {})) - set(handlers.get(req.proto, {}))
    if current == "static" and req.proto != "static":
        gone |= set(STATIC_ONLY)
    ops += [UciOp("delete", f"{p}.{name}") for name in sorted(gone) if name in set_here]
    return ops


def compile_interface(
    req: InterfaceRequest,
    state: NetworkState,
    uci: Mapping[str, str],
    handlers: Mapping[str, Mapping[str, str]],
    router_name: str,
) -> tuple[list[UciOp], list[str], list[str]]:
    """uci operations, secrets (hidden in the preview) and warnings for one interface change."""
    _existing(req, state)
    _refuse_own(req, state, router_name)
    p = f"network.{req.name}"
    if req.delete:
        return [UciOp("delete", p)], [], []
    conf = state.conf(req.name)
    current = conf.proto if conf is not None else "none"
    set_here = options(uci, "network", req.name)
    ops: list[UciOp] = []
    warnings: list[str] = []
    if req.create:
        check_proto(req.proto or "none", handlers, router_name)
        ops += [UciOp("set", p, "interface"), UciOp("set", f"{p}.proto", req.proto or "none")]
        warnings.append(f"Put {req.name} in a firewall zone on the Firewall screen (Zones).")
    else:
        ops += _proto_ops(req, current, set_here, handlers, router_name)
    proto = req.proto or current
    if req.device is not None:
        ops.append(UciOp("set", f"{p}.device", req.device))
    if req.address is not None:
        ops.append(UciOp("set", f"{p}.ipaddr", str(parse_cidr(req.address))))
        if "netmask" in set_here:
            ops.append(UciOp("delete", f"{p}.netmask"))
    elif proto == "static" and current != "static":
        raise ValueError(f"Give {req.name} an address, e.g. 192.168.1.2/24")
    if req.gateway is not None:
        ops.append(
            UciOp("set", f"{p}.gateway", _ipv4(req.gateway))
            if req.gateway
            else UciOp("delete", f"{p}.gateway")
        )
    if req.dns is not None:
        ops += [UciOp("delete", f"{p}.dns"), *(UciOp("add_list", f"{p}.dns", _ip(d)) for d in req.dns)]
    if req.mtu is not None:
        if not MTU_MIN <= req.mtu <= MTU_MAX:
            raise ValueError(f"MTU is {MTU_MIN} to {MTU_MAX}")
        ops.append(UciOp("set", f"{p}.mtu", str(req.mtu)))
    if req.bridge_ports is not None:
        ops += _bridge_ops(req, state, conf.device if conf else req.device)
    secrets: list[str] = []
    if req.edits:
        edit_ops, secrets = forms.compile_edits(
            "network", req.edits, interface_rows(state, uci, handlers, req.name)
        )
        ops += edit_ops
    return ops, secrets, warnings


def _bridge_ops(req: InterfaceRequest, state: NetworkState, device: str | None) -> list[UciOp]:
    bridge = next((d for d in state.devices if d.name == device and d.type == "bridge"), None)
    if bridge is None:
        raise ValueError(f"{device or req.name} is not a bridge")
    path = f"network.{bridge.section}.ports"
    return [UciOp("delete", path), *(UciOp("add_list", path, port) for port in req.bridge_ports or ())]


def target_host(req: InterfaceRequest, state: NetworkState, rec: RouterRecord) -> str | None:
    """Where the app reconnects after the change: lan's new address when it changes and the router was
    added by that address; None keeps the router's host."""
    if req.name != state.own_interface or req.address is None or rec.host != state.router_ip:
        return None
    new = parse_cidr(req.address).ip
    return new if new != state.router_ip else None


def pc_warning(state: NetworkState, address: str | None) -> list[str]:
    if address is None or state.pc_ip is None:
        return []
    new: Address = parse_cidr(address)
    network = ipaddress.ip_interface(str(new)).network
    if ipaddress.ip_address(state.pc_ip) in network:
        return []
    return [
        f"This PC ({state.pc_ip}) is not in {network}: the app reaches {new.ip} only through a route, "
        "otherwise the change rolls back."
    ]
