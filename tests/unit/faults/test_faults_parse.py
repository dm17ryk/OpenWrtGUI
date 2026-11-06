"""conntrack flows, and the target's RTP ports read from them."""

from __future__ import annotations

from openwrtgui.faults.parse import Flow, parse_conntrack, rtp_ports

CONNTRACK = (
    "udp      17 29 src=192.168.1.30 dst=203.0.113.5 sport=4000 dport=31000 packets=120 bytes=24000 "
    "src=203.0.113.5 dst=192.168.2.10 sport=31000 dport=4000 packets=118 bytes=23600 [ASSURED] mark=0 use=1\n"
    "udp      17 20 src=192.168.1.30 dst=192.168.1.1 sport=5060 dport=5060 packets=4 bytes=2000 "
    "src=192.168.1.1 dst=192.168.1.30 sport=5060 dport=5060 packets=4 bytes=1900 mark=0 use=1\n"
    "udp      17 25 src=203.0.113.9 dst=192.168.1.30 sport=40000 dport=4002 packets=50 bytes=9000 "
    "src=192.168.1.30 dst=203.0.113.9 sport=4002 dport=40000 packets=49 bytes=8800 mark=0 use=1\n"
    "udp      17 15 src=192.168.1.30 dst=192.168.1.1 sport=34567 dport=53 packets=1 bytes=60 "
    "src=192.168.1.1 dst=192.168.1.30 sport=53 dport=34567 packets=1 bytes=120 mark=0 use=1\n"
    "conntrack v1.4.8 (conntrack-tools): 4 flow entries have been shown.\n"
)


def test_parse_conntrack_original_direction() -> None:
    flows = parse_conntrack(CONNTRACK)
    assert flows[0] == Flow("udp", "192.168.1.30", "203.0.113.5", 4000, 31000)
    assert len(flows) == 4


def test_rtp_ports_from_conntrack() -> None:
    """The target's side of each UDP flow, except DNS, DHCP, NTP and SIP."""
    assert rtp_ports(parse_conntrack(CONNTRACK), "192.168.1.30") == (4000, 4002)
    assert rtp_ports(parse_conntrack(CONNTRACK), "192.168.1.99") == ()
