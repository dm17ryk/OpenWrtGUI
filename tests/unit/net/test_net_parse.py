"""Network, DHCP and route parsers, on AP2's real text (read 2026-11-05)."""

from __future__ import annotations

import json

import pytest

from openwrtgui.net.model import Address, LiveRoute, parse_cidr
from openwrtgui.net.parse import (
    devices,
    dhcp_sections,
    dnsmasq,
    hosts,
    interfaces,
    parse_host_hints,
    parse_interface_dump,
    parse_ip_routes,
    parse_ip_rules,
    parse_leases,
    parse_ssh_connection,
    routes,
    rules,
    sections,
)
from openwrtgui.uci import parse_uci_show

NETWORK = """network.loopback=interface
network.loopback.device='lo'
network.loopback.proto='static'
network.loopback.ipaddr='127.0.0.1/8'
network.cfg030f15=device
network.cfg030f15.name='br-lan'
network.cfg030f15.type='bridge'
network.cfg030f15.ports='eth0.1'
network.lan=interface
network.lan.device='br-lan'
network.lan.proto='static'
network.lan.ipaddr='192.168.1.2/24'
network.lan.ip6assign='60'
network.wan=interface
network.wan.device='eth0.2'
network.wan.proto='dhcp'
network.lte=interface
network.lte.device='/dev/cdc-wdm0'
network.lte.metric='20'
network.lte.proto='qmi'
network.lte.mtu='1420'
network.cfg0b1ec7=switch_vlan
network.cfg0b1ec7.device='switch0'
network.cfg0b1ec7.vlan='1'
network.cfg0b1ec7.ports='0 1 2 3 6t'
"""
DHCP = """dhcp.cfg01411c=dnsmasq
dhcp.cfg01411c.domain='lan'
dhcp.cfg01411c.local='/lan/'
dhcp.cfg01411c.rebind_protection='1'
dhcp.lan=dhcp
dhcp.lan.interface='lan'
dhcp.lan.start='100'
dhcp.lan.limit='150'
dhcp.lan.leasetime='12h'
dhcp.lan.ra='disabled'
dhcp.lan.dhcpv6='disabled'
dhcp.lan.ignore='1'
dhcp.wan=dhcp
dhcp.wan.interface='wan'
dhcp.wan.ignore='1'
dhcp.cfg0a1b2c=host
dhcp.cfg0a1b2c.name='panel'
dhcp.cfg0a1b2c.mac='F4:12:FA:F3:57:68'
dhcp.cfg0a1b2c.ip='192.168.1.30'
dhcp.cfg0b1b2c=host
dhcp.cfg0b1b2c.mac='aa:bb:cc:dd:ee:01' 'aa:bb:cc:dd:ee:02'
dhcp.cfg0b1b2c.ignore='1'
"""


def test_interfaces_ap2() -> None:
    ifs = {i.name: i for i in interfaces(parse_uci_show(NETWORK))}
    assert ifs["lan"].address == Address("192.168.1.2", 24) and ifs["lan"].device == "br-lan"
    assert ifs["lan"].proto == "static" and ifs["lan"].auto is True
    assert ifs["wan"].proto == "dhcp" and ifs["wan"].address is None
    assert ifs["lte"].mtu == 1420
    assert list(ifs) == ["loopback", "lan", "wan", "lte"]


def test_devices_and_sections() -> None:
    uci = parse_uci_show(NETWORK)
    assert devices(uci)[0].ports == ("eth0.1",) and devices(uci)[0].name == "br-lan"
    assert sections(uci, "network", "switch_vlan") == ["cfg0b1ec7"]


def test_legacy_netmask_reads_as_prefix() -> None:
    uci = parse_uci_show(
        "network.lan=interface\nnetwork.lan.proto='static'\n"
        "network.lan.ipaddr='10.0.0.1'\nnetwork.lan.netmask='255.255.255.0'\n"
    )
    assert interfaces(uci)[0].address == Address("10.0.0.1", 24)


def test_auto_off_and_dns_list() -> None:
    uci = parse_uci_show(
        "network.x=interface\nnetwork.x.proto='static'\nnetwork.x.auto='0'\n"
        "network.x.dns='1.1.1.1' '8.8.8.8'\n"
    )
    x = interfaces(uci)[0]
    assert x.auto is False and x.dns == ("1.1.1.1", "8.8.8.8")


def test_bare_address_is_refused() -> None:
    with pytest.raises(ValueError, match=r"Write the address with its prefix, e\.g\. 192\.168\.1\.2/24"):
        parse_cidr("192.168.1.12")
    with pytest.raises(ValueError, match="10.0.0/33 is not an IPv4 network"):
        parse_cidr("10.0.0/33")
    assert str(parse_cidr("192.168.1.12/24")) == "192.168.1.12/24"
    assert parse_cidr("fd00::1/64", 6) == Address("fd00::1", 64)


def test_dhcp_ap2() -> None:
    uci = parse_uci_show(DHCP)
    lan = next(d for d in dhcp_sections(uci) if d.interface == "lan")
    assert (lan.section, lan.enabled, lan.start, lan.limit, lan.leasetime) == ("lan", False, 100, 150, "12h")
    assert (lan.dhcpv6, lan.ra, lan.options) == ("disabled", "disabled", ())
    dns = dnsmasq(uci)
    assert dns is not None and dns.section == "cfg01411c" and dns.values["domain"] == "lan"


def test_hosts() -> None:
    panel, both = hosts(parse_uci_show(DHCP))
    assert (panel.section, panel.name, panel.macs, panel.ip, panel.gets_address) == (
        "cfg0a1b2c",
        "panel",
        ("f4:12:fa:f3:57:68",),
        "192.168.1.30",
        True,
    )
    assert both.macs == ("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02") and both.gets_address is False


def test_routes_and_rules() -> None:
    uci = parse_uci_show(
        "network.cfg1=route\nnetwork.cfg1.interface='lan'\nnetwork.cfg1.target='10.10.0.0/16'\n"
        "network.cfg1.gateway='192.168.1.1'\nnetwork.cfg1.metric='5'\n"
        "network.cfg2=route\nnetwork.cfg2.interface='lan'\nnetwork.cfg2.target='10.20.0.0'\n"
        "network.cfg2.netmask='255.255.0.0'\nnetwork.cfg2.disabled='1'\n"
        "network.cfg3=rule\nnetwork.cfg3.src='192.168.5.0/24'\nnetwork.cfg3.lookup='100'\nnetwork.cfg3.priority='90'\n"
    )
    r1, r2 = routes(uci)
    assert (r1.kind, r1.interface, r1.target, r1.gateway, r1.metric, r1.disabled) == (
        "route",
        "lan",
        "10.10.0.0/16",
        "192.168.1.1",
        5,
        False,
    )
    assert r2.target == "10.20.0.0/16" and r2.disabled
    (rule,) = rules(uci)
    assert (rule.src, rule.lookup, rule.priority) == ("192.168.5.0/24", "100", 90)


DUMP = {
    "interface": [
        {
            "interface": "lan",
            "up": True,
            "dynamic": False,
            "uptime": 1786039,
            "l3_device": "br-lan",
            "proto": "static",
            "device": "br-lan",
            "ipv4-address": [{"address": "192.168.1.2", "mask": 24}],
            "ipv6-address": [],
        },
        {"interface": "lte", "up": True, "dynamic": False, "l3_device": "wwan0", "proto": "qmi"},
        {
            "interface": "lte_4",
            "up": False,
            "pending": True,
            "dynamic": True,
            "proto": "dhcp",
            "device": "wwan0",
        },
        {
            "interface": "wan",
            "up": False,
            "dynamic": False,
            "proto": "dhcp",
            "device": "eth0.2",
            "errors": [{"subsystem": "dhcp", "code": "NO_LINK"}],
        },
    ]
}


def test_interface_dump_dynamic() -> None:
    live = {i.name: i for i in parse_interface_dump(DUMP)}
    assert live["lan"].ipv4 == (Address("192.168.1.2", 24),) and live["lan"].uptime_s == 1786039
    assert live["lte_4"].dynamic and live["lte_4"].parent == "lte"
    assert live["lan"].parent is None and live["wan"].errors == ("dhcp: NO_LINK",)


def test_leases() -> None:
    leases = parse_leases(
        {
            "dhcp_leases": [
                {
                    "expires": 43000,
                    "hostname": "panel",
                    "macaddr": "F4:12:FA:F3:57:68",
                    "ipaddr": "192.168.1.30",
                }
            ],
            "dhcp6_leases": [{"expires": 3600, "hostname": "pc", "duid": "0001", "ip6addr": "fd00::5"}],
        }
    )
    assert [(lease.family, lease.mac, lease.ip, lease.hostname, lease.expires_s) for lease in leases] == [
        (4, "f4:12:fa:f3:57:68", "192.168.1.30", "panel", 43000),
        (6, None, "fd00::5", "pc", 3600),
    ]


def test_host_hints() -> None:
    hints = parse_host_hints(
        {
            "08:3A:88:5C:A8:39": {"ipaddrs": ["192.168.1.10"], "ip6addrs": []},
            "F4:12:FA:F3:57:68": {"name": "panel", "ipaddrs": ["192.168.1.30"]},
            "00:0C:43:76:20:16": {"ipaddrs": [], "ip6addrs": ["fe80::1"]},
        }
    )
    assert hints == {"08:3a:88:5c:a8:39": "192.168.1.10", "f4:12:fa:f3:57:68": "panel"}


def test_ip_routes_json() -> None:
    text = json.dumps(
        [
            {
                "dst": "192.168.1.0/24",
                "dev": "br-lan",
                "protocol": "kernel",
                "scope": "link",
                "prefsrc": "192.168.1.2",
            },
            {"type": "local", "dst": "127.0.0.1", "dev": "lo", "table": "local", "protocol": "kernel"},
            {"dst": "default", "gateway": "192.168.1.1", "dev": "br-lan", "metric": 10},
        ]
    )
    assert parse_ip_routes(text, 4) == [
        LiveRoute(4, "192.168.1.0/24", None, "br-lan", "main", "kernel", None, "unicast"),
        LiveRoute(4, "127.0.0.1", None, "lo", "local", "kernel", None, "local"),
        LiveRoute(4, "default", "192.168.1.1", "br-lan", "main", None, 10, "unicast"),
    ]


def test_ip_rules_json() -> None:
    text = json.dumps(
        [
            {"priority": 0, "src": "all", "table": "local"},
            {"priority": 90, "src": "192.168.5.0", "srclen": 24, "table": "100"},
        ]
    )
    assert [(r.priority, r.src, r.lookup) for r in parse_ip_rules(text, 4)] == [
        (0, "all", "local"),
        (90, "192.168.5.0/24", "100"),
    ]


def test_ssh_connection() -> None:
    assert parse_ssh_connection("192.168.1.10 51234 192.168.1.2 22\n") == ("192.168.1.10", "192.168.1.2")
    assert parse_ssh_connection("\n") is None
