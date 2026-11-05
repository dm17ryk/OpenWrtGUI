"""What the Network & DHCP screen shows for one router, read in a few execs (plan v0.3, "Reads")."""

from __future__ import annotations

import json
from dataclasses import dataclass

from openwrtgui.net import commands as c
from openwrtgui.net.model import (
    DeviceConf,
    DhcpConf,
    DnsConf,
    HostConf,
    InterfaceConf,
    InterfaceLive,
    RouteConf,
    RuleConf,
)
from openwrtgui.net.parse import (
    devices,
    dhcp_sections,
    dnsmasq,
    hosts,
    interfaces,
    parse_interface_dump,
    parse_ssh_connection,
    routes,
    rules,
)
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.transport.base import Transport
from openwrtgui.uci import parse_uci_show

PROTO_LABELS = {
    "static": "Static",
    "dhcp": "DHCP client",
    "none": "No address",
    "qmi": "LTE (QMI)",
    "ppp": "PPP",
    "pppoe": "PPPoE",
    "dhcpv6": "DHCPv6 client",
    "wwan": "Mobile (wwan)",
}


def proto_label(name: str) -> str:
    return PROTO_LABELS.get(name, name)


@dataclass(frozen=True)
class ProtoView:
    name: str
    label: str
    options: int


@dataclass(frozen=True)
class InterfaceView:
    conf: InterfaceConf | None  # None: made by netifd at run time (not in /etc/config/network)
    live: InterfaceLive | None
    own: bool
    dynamic_parent: str | None


@dataclass(frozen=True)
class NetworkState:
    router_id: str
    interfaces: tuple[InterfaceView, ...]
    devices: tuple[DeviceConf, ...]
    protocols: tuple[ProtoView, ...]
    own_interface: str | None
    pc_ip: str | None
    router_ip: str | None
    dhcp: tuple[DhcpConf, ...]
    hosts: tuple[HostConf, ...]
    dns: DnsConf | None
    routes: tuple[RouteConf, ...]
    rules: tuple[RuleConf, ...]

    def conf(self, name: str) -> InterfaceConf | None:
        return next((v.conf for v in self.interfaces if v.conf is not None and v.conf.name == name), None)

    def dynamic(self, name: str) -> InterfaceView | None:
        return next((v for v in self.interfaces if v.conf is None and v.live and v.live.name == name), None)


def protocols(desc: SelfDescription) -> dict[str, dict[str, str]]:
    """The router's protocol handlers and their typed options; `none` is netifd's own and always there."""
    return {"none": {}, **desc.protocols}


async def _stdout(t: Transport, command: str) -> str:
    r = await t.run(command)
    return r.stdout if r.ok else ""


async def read_network(
    t: Transport, router_id: str, desc: SelfDescription
) -> tuple[NetworkState, dict[str, str]]:
    uci = parse_uci_show(await _stdout(t, c.UCI_NETWORK)) | parse_uci_show(await _stdout(t, c.UCI_DHCP))
    dump = await _stdout(t, c.INTERFACE_DUMP)
    live = {i.name: i for i in parse_interface_dump(json.loads(dump) if dump.strip() else {})}
    pair = parse_ssh_connection(await _stdout(t, c.SSH_CONNECTION))
    pc_ip, router_ip = pair if pair else (None, None)
    confs = interfaces(uci)
    own = next(
        (
            i.name
            for i in confs
            if router_ip and i.name in live and any(a.ip == router_ip for a in live[i.name].ipv4)
        ),
        None,
    )
    views = [InterfaceView(i, live.get(i.name), i.name == own, None) for i in confs]
    configured = {i.name for i in confs}
    views += [InterfaceView(None, v, False, v.parent) for v in live.values() if v.name not in configured]
    handlers = protocols(desc)
    state = NetworkState(
        router_id=router_id,
        interfaces=tuple(views),
        devices=tuple(devices(uci)),
        protocols=tuple(ProtoView(n, proto_label(n), len(o)) for n, o in handlers.items()),
        own_interface=own,
        pc_ip=pc_ip,
        router_ip=router_ip,
        dhcp=tuple(dhcp_sections(uci)),
        hosts=tuple(hosts(uci)),
        dns=dnsmasq(uci),
        routes=tuple(routes(uci)),
        rules=tuple(rules(uci)),
    )
    return state, uci
