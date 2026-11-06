"""The `firewall` uci config as fw4 reads it: zones, forwardings, rules, redirects, NAT, IP sets, includes."""

from __future__ import annotations

from openwrtgui.fw.parse import firewall_conf
from openwrtgui.uci import parse_uci_show

# OpenWrt's default /etc/config/firewall (uci -X show), plus one redirect, NAT rule, IP set and include.
DEFAULT = """firewall.cfg01e63d=defaults
firewall.cfg01e63d.syn_flood='1'
firewall.cfg01e63d.input='REJECT'
firewall.cfg01e63d.output='ACCEPT'
firewall.cfg01e63d.forward='REJECT'
firewall.cfg02dc81=zone
firewall.cfg02dc81.name='lan'
firewall.cfg02dc81.network='lan'
firewall.cfg02dc81.input='ACCEPT'
firewall.cfg02dc81.output='ACCEPT'
firewall.cfg02dc81.forward='ACCEPT'
firewall.cfg03dc81=zone
firewall.cfg03dc81.name='wan'
firewall.cfg03dc81.network='wan' 'wan6'
firewall.cfg03dc81.input='REJECT'
firewall.cfg03dc81.output='ACCEPT'
firewall.cfg03dc81.forward='REJECT'
firewall.cfg03dc81.masq='1'
firewall.cfg03dc81.mtu_fix='1'
firewall.cfg04ad58=forwarding
firewall.cfg04ad58.src='lan'
firewall.cfg04ad58.dest='wan'
firewall.cfg0592bd=rule
firewall.cfg0592bd.name='Allow-DHCP-Renew'
firewall.cfg0592bd.src='wan'
firewall.cfg0592bd.proto='udp'
firewall.cfg0592bd.dest_port='68'
firewall.cfg0592bd.target='ACCEPT'
firewall.cfg0592bd.family='ipv4'
firewall.cfg0692bd=rule
firewall.cfg0692bd.name='Allow-Ping'
firewall.cfg0692bd.src='wan'
firewall.cfg0692bd.proto='icmp'
firewall.cfg0692bd.icmp_type='echo-request'
firewall.cfg0692bd.family='ipv4'
firewall.cfg0692bd.target='ACCEPT'
firewall.cfg0792bd=rule
firewall.cfg0792bd.name='Block-panel'
firewall.cfg0792bd.src='lan'
firewall.cfg0792bd.src_ip='192.168.1.20' '192.168.1.21'
firewall.cfg0792bd.enabled='0'
firewall.cfg0792bd.limit='10/sec'
firewall.cfg08aa01=redirect
firewall.cfg08aa01.name='panel-web'
firewall.cfg08aa01.src='wan'
firewall.cfg08aa01.src_dport='8080'
firewall.cfg08aa01.dest='lan'
firewall.cfg08aa01.dest_ip='192.168.1.20'
firewall.cfg08aa01.dest_port='80'
firewall.cfg08aa01.proto='tcp'
firewall.cfg09bb02=nat
firewall.cfg09bb02.name='snat-lab'
firewall.cfg09bb02.src='wan'
firewall.cfg09bb02.src_ip='192.168.3.0/24'
firewall.cfg09bb02.target='SNAT'
firewall.cfg09bb02.snat_ip='10.0.0.18'
firewall.cfg0acc03=ipset
firewall.cfg0acc03.name='panels'
firewall.cfg0acc03.match='src_mac'
firewall.cfg0acc03.entry='f4:12:fa:f3:57:68' 'e4:5f:01:aa:bb:01'
firewall.owg_inet_owg_test=include
firewall.owg_inet_owg_test.type='nftables'
firewall.owg_inet_owg_test.path='/etc/owg/nft/inet-owg_test.nft'
firewall.owg_inet_owg_test.position='ruleset-post'
"""


def test_firewall_conf_defaults() -> None:
    conf = firewall_conf(parse_uci_show(DEFAULT))
    assert conf.defaults is not None and conf.defaults.values["syn_flood"] == "1"
    lan, wan = conf.zones
    assert (lan.section, lan.name, lan.networks) == ("cfg02dc81", "lan", ("lan",))
    assert (lan.input, lan.output, lan.forward, lan.masq) == ("ACCEPT", "ACCEPT", "ACCEPT", False)
    assert (wan.networks, wan.input, wan.forward, wan.masq, wan.mtu_fix) == (
        ("wan", "wan6"),
        "REJECT",
        "REJECT",
        True,
        True,
    )
    assert [(f.src, f.dest, f.enabled) for f in conf.forwardings] == [("lan", "wan", True)]
    ping = next(r for r in conf.rules if r.name == "Allow-Ping")
    assert (ping.src, ping.dest, ping.proto, ping.icmp_type, ping.target) == (
        "wan",
        None,
        "icmp",
        ("echo-request",),
        "ACCEPT",
    )
    block = next(r for r in conf.rules if r.name == "Block-panel")
    assert block.src_ip == ("192.168.1.20", "192.168.1.21") and not block.enabled
    assert block.target == "DROP"  # fw4's default rule target
    assert block.others == {"limit": "10/sec"}


def test_redirect_nat_ipset_include() -> None:
    conf = firewall_conf(parse_uci_show(DEFAULT))
    (fwd,) = conf.redirects
    assert (fwd.name, fwd.src_dport, fwd.dest_ip, fwd.dest_port, fwd.target) == (
        "panel-web",
        "8080",
        "192.168.1.20",
        "80",
        "DNAT",
    )
    (nat,) = conf.nats
    assert (nat.name, nat.src_ip, nat.target, nat.snat_ip) == (
        "snat-lab",
        "192.168.3.0/24",
        "SNAT",
        "10.0.0.18",
    )
    (ipset,) = conf.ipsets
    assert (ipset.name, ipset.family, ipset.match, ipset.entries) == (
        "panels",
        "ipv4",
        ("src_mac",),
        ("f4:12:fa:f3:57:68", "e4:5f:01:aa:bb:01"),
    )
    (inc,) = conf.includes
    assert (inc.section, inc.type, inc.path, inc.position) == (
        "owg_inet_owg_test",
        "nftables",
        "/etc/owg/nft/inet-owg_test.nft",
        "ruleset-post",
    )


def test_unset_zone_policy_follows_the_defaults_section() -> None:
    """fw4 takes a zone's unset policy from the defaults section, and DROP when that has none either."""
    uci = parse_uci_show(
        "firewall.d=defaults\nfirewall.d.input='REJECT'\n"
        "firewall.z=zone\nfirewall.z.name='guest'\nfirewall.z.network='guest'\n"
    )
    (guest,) = firewall_conf(uci).zones
    assert (guest.input, guest.output, guest.forward) == ("REJECT", "DROP", "DROP")
