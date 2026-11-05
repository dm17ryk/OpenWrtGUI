"""The network and switch parsers against AP2's real answers (recorded read-only, 2026-11-05)."""

import json
from pathlib import Path

from openwrtgui.net import commands as c
from openwrtgui.net.model import Address
from openwrtgui.net.parse import (
    devices,
    dhcp_sections,
    interfaces,
    parse_interface_dump,
    parse_ip_routes,
    parse_ssh_connection,
)
from openwrtgui.ports.parse import parse_arl, parse_swconfig_help, parse_swconfig_show, switch_vlans
from openwrtgui.transport.fake import load_commands
from openwrtgui.uci import parse_uci_show

AP2 = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
NET = load_commands(AP2 / "network.json")
UCI = parse_uci_show(NET[c.UCI_NETWORK].stdout) | parse_uci_show(NET[c.UCI_DHCP].stdout)


def test_every_read_answered() -> None:
    assert set(NET) == set(c.network_reads("switch0"))
    assert all(r.exit_status == 0 for r in NET.values())


def test_lan_is_static_on_a_bridge_over_vlan_1() -> None:
    ifs = {i.name: i for i in interfaces(UCI)}
    assert ifs["lan"].proto == "static" and ifs["lan"].address == Address("192.168.1.2", 24)
    assert ifs["lan"].device == "br-lan"
    bridge = next(d for d in devices(UCI) if d.name == "br-lan")
    assert bridge.type == "bridge" and bridge.ports == ("eth0.1",)
    assert (ifs["wan"].proto, ifs["wan"].device) == ("dhcp", "eth0.2")
    assert ifs["lte"].proto == "qmi"


def test_dump_has_lan_up_and_lte_4_made_by_lte() -> None:
    live = {i.name: i for i in parse_interface_dump(json.loads(NET[c.INTERFACE_DUMP].stdout))}
    assert live["lan"].up and live["lan"].ipv4 == (Address("192.168.1.2", 24),)
    if "lte_4" in live:
        assert live["lte_4"].dynamic and live["lte_4"].parent == "lte"


def test_switch_vlans_ports_and_attributes() -> None:
    vlans = {v.vlan: v.members for v in switch_vlans(UCI)}
    assert vlans[1] == ((0, False), (1, False), (2, False), (3, False), (6, True))
    assert vlans[2] == ((4, False), (6, True))
    sw = parse_swconfig_show("switch0", NET[c.swconfig_show("switch0")].stdout)
    p3 = next(p for p in sw.ports if p.num == 3)
    assert (p3.link, p3.speed_mbps, p3.full_duplex, p3.enabled) == (True, 100, True, True)
    assert next(p for p in sw.ports if p.num == 6).enabled is None  # the CPU port: "???"
    h = parse_swconfig_help(NET[c.swconfig_help("switch0")].stdout)
    assert (h.ports, h.cpu_port, h.vlans) == (8, 6, 16)
    assert {"enable", "enable_mirror_rx", "enable_mirror_tx"} <= h.port_attrs
    assert "mirror_monitor_port" in h.global_attrs
    assert parse_arl(NET[c.swconfig_arl("switch0")].stdout) == {}  # mt7620: the ARL table stays empty
    features = json.loads(NET[c.switch_features("switch0")].stdout)
    assert features["mirror_option"] == "enable_mirror_rx"


def test_dhcp_server_is_off_on_lan() -> None:
    lan = next(d for d in dhcp_sections(UCI) if d.interface == "lan")
    assert (lan.enabled, lan.start, lan.limit, lan.leasetime) == (False, 100, 150, "12h")


def test_ssh_connection_names_the_router_address() -> None:
    pair = parse_ssh_connection(NET[c.SSH_CONNECTION].stdout)
    assert pair is not None and pair[1] == "192.168.1.2"


def test_main_route_to_the_lan() -> None:
    routes = parse_ip_routes(NET[c.ip_routes(4)].stdout, 4)
    assert any(r.dst == "192.168.1.0/24" and r.dev == "br-lan" and r.table == "main" for r in routes)


def test_services() -> None:
    assert json.loads(NET[c.service_list("dnsmasq")].stdout)["dnsmasq"]["instances"]
    assert json.loads(NET[c.service_list("wifi-mirror")].stdout) == {}
