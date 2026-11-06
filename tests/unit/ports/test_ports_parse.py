"""swconfig parsers, on AP2's real text (switch0, mt7620, read 2026-11-05)."""

from __future__ import annotations

from openwrtgui.ports.parse import (
    parse_arl,
    parse_arp,
    parse_members,
    parse_swconfig_help,
    parse_swconfig_show,
    render_members,
    switch_conf,
    switch_ports,
    switch_vlans,
)
from openwrtgui.uci import parse_uci_show

SHOW = (
    "Global attributes:\n\tenable_vlan: 1\n\tmib: Switch MIB counters\nPPE_AC_BCNT0: 0\nGDM2_RX_LERCNT: 3\n\n"
    "\tmirror_monitor_port: 0\n\tarl_table: address resolution table\n\n"
    "Port 3:\n\tmib: Port 3 MIB counters\nTxGPC      : 42001\nRxEPC2     : 502\n\n"
    "\tenable_mirror_rx: 0\n\tenable_mirror_tx: 1\n\tenable: 1\n\tpvid: 1\n"
    "\tlink: port:3 link:up speed:100baseT full-duplex \n"
    "Port 4:\n\tenable_mirror_rx: 0\n\tenable_mirror_tx: 0\n\tenable: 0\n\tpvid: 2\n"
    "\tlink: port:4 link:down\n"
    "Port 5:\n\tenable_mirror_rx: 0\n\tenable_mirror_tx: 0\n\tenable: ???\n\tpvid: 0\n"
    "\tlink: port:5 link:down\n"
    "Port 6:\n\tenable: ???\n\tpvid: 0\n\tlink: port:6 link:up speed:1000baseT full-duplex \n"
    "VLAN 1:\n\tvid: 1\n\tports: 0 1 2 3 6t \nVLAN 2:\n\tvid: 2\n\tports: 4 6t \n"
)
HELP = (
    "switch0: mt7620(mt7620), ports: 8 (cpu @ 6), vlans: 16\n     --switch\n"
    "\tAttribute 1 (int): enable_vlan (VLAN mode (1:enabled))\n"
    "\tAttribute 3 (int): mirror_monitor_port (Mirror monitor port)\n"
    "\tAttribute 4 (string): arl_table (Get ARL table)\n"
    "     --vlan\n\tAttribute 1 (int): vid (VLAN ID (0-4094))\n"
    "     --port\n\tAttribute 2 (int): enable_mirror_rx (Enable mirroring of RX packets)\n"
    "\tAttribute 3 (int): enable_mirror_tx (Enable mirroring of TX packets)\n"
    "\tAttribute 4 (int): enable (Enable the external PHY)\n\tAttribute 5 (int): pvid (Primary VLAN ID)\n"
)


def test_swconfig_show_ap2() -> None:
    sw = parse_swconfig_show("switch0", SHOW)
    ports = {p.num: p for p in sw.ports}
    p3 = ports[3]
    assert (p3.enabled, p3.link, p3.speed_mbps, p3.full_duplex, p3.pvid) == (True, True, 100, True, 1)
    assert (p3.mirror_rx, p3.mirror_tx) == (False, True)
    assert ports[4].enabled is False and ports[4].link is False and ports[4].speed_mbps is None
    assert ports[5].enabled is None
    assert ports[6].speed_mbps == 1000
    assert sw.vlans[0].vlan == 1 and sw.vlans[0].vid == 1
    assert sw.vlans[0].members == ((0, False), (1, False), (2, False), (3, False), (6, True))
    assert sw.vlans[1].members == ((4, False), (6, True))
    assert (sw.enable_vlan, sw.mirror_monitor_port) == (True, 0)


def test_swconfig_help_ap2() -> None:
    h = parse_swconfig_help(HELP)
    assert (h.ports, h.cpu_port, h.vlans) == (8, 6, 16)
    assert {"enable", "enable_mirror_rx", "enable_mirror_tx", "pvid"} <= h.port_attrs
    assert {"mirror_monitor_port", "arl_table"} <= h.global_attrs and "vid" not in h.port_attrs


def test_members_round_trip() -> None:
    assert render_members(dict(parse_members("6t 0 3"))) == "0 3 6t"
    assert parse_members("") == ()


def test_arl_and_arp() -> None:
    assert parse_arl("address resolution table\n\n") == {}
    assert parse_arl("Port 3: MAC 08:3A:88:5C:A8:39\nport 2: mac aa:bb:cc:dd:ee:ff\n") == {
        "08:3a:88:5c:a8:39": 3,
        "aa:bb:cc:dd:ee:ff": 2,
    }
    arp = (
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.10     0x1         0x2         08:3a:88:5c:a8:39     *        br-lan\n"
        "192.168.1.99     0x1         0x0         00:00:00:00:00:00     *        br-lan\n"
    )
    assert parse_arp(arp) == {"192.168.1.10": "08:3a:88:5c:a8:39"}


def test_switch_uci() -> None:
    uci = parse_uci_show(
        "network.cfg0a3777=switch\nnetwork.cfg0a3777.name='switch0'\nnetwork.cfg0a3777.mirror_monitor_port='1'\n"
        "network.cfg0b1ec7=switch_vlan\nnetwork.cfg0b1ec7.device='switch0'\nnetwork.cfg0b1ec7.vlan='1'\n"
        "network.cfg0b1ec7.ports='0 1 2 3 6t'\n"
        "network.cfg0d=switch_port\nnetwork.cfg0d.device='switch0'\nnetwork.cfg0d.port='2'\n"
        "network.cfg0d.enable_mirror_rx='1'\n"
    )
    conf = switch_conf(uci, "switch0")
    assert conf is not None and (conf.section, conf.mirror_monitor_port) == ("cfg0a3777", 1)
    (vlan,) = switch_vlans(uci)
    assert (vlan.section, vlan.device, vlan.vlan, vlan.vid) == ("cfg0b1ec7", "switch0", 1, None)
    assert vlan.members[-1] == (6, True)
    (port,) = switch_ports(uci)
    assert (port.section, port.port, port.mirror_rx, port.mirror_tx) == ("cfg0d", 2, True, False)
    assert switch_conf(uci, "switch1") is None
