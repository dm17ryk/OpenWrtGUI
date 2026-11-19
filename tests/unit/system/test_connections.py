"""Connections (v1.2a Task 6): each entry's conntrack helper, the table's size, and the SIP ALG state."""

from __future__ import annotations

from openwrtgui.fw.commands import NFT_TEXT
from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.system.commands import CONNTRACK_SIZE
from openwrtgui.system.parse import parse_conntrack, parse_conntrack_size, parse_sip_alg
from openwrtgui.system.state import SipAlg

LINES = (
    "ipv4     2 udp      17 175 src=10.0.0.5 dst=10.0.0.9 sport=5060 dport=5060 packets=9 bytes=4200 "
    "src=10.0.0.9 dst=10.0.0.5 sport=5060 dport=5060 packets=8 bytes=3900 [ASSURED] mark=0 helper=sip use=2\n"
    "ipv6     10 tcp      6 431999 ESTABLISHED src=fd00::5 dst=fd00::1 sport=50000 dport=22 packets=3 "
    "bytes=300 src=fd00::1 dst=fd00::5 sport=22 dport=50000 packets=2 bytes=200 [ASSURED] use=1\n"
    "ipv4     2 icmp     1 29 src=10.0.0.5 dst=10.0.0.1 type=8 code=0 id=7 packets=1 bytes=84 "
    "src=10.0.0.1 dst=10.0.0.5 type=0 code=0 id=7 packets=1 bytes=84 use=1\n"
    "ipv4     2 udp      17 29 src=10.0.0.5 dst=10.0.0.1 sport=5353 dport=53 packets=1 bytes=60 [UNREPLIED] "
    "src=10.0.0.1 dst=10.0.0.5 sport=53 dport=5353 packets=0 bytes=0 use=2\n"
)


def test_conntrack_helper_and_odd_lines() -> None:
    rows = parse_conntrack(LINES)
    assert [(r.proto, r.helper) for r in rows] == [
        ("udp", "sip"),
        ("tcp", None),
        ("icmp", None),
        ("udp", None),
    ]
    assert (rows[1].src, rows[1].dport, rows[1].state) == ("fd00::5", 22, "ESTABLISHED")
    assert (rows[2].sport, rows[2].dport, rows[2].bytes) == (None, None, 168)


def test_conntrack_size() -> None:
    assert parse_conntrack_size("37\n16384\n") == (37, 16384)
    assert parse_conntrack_size("37\n") == (None, None)  # a short read gives neither
    assert parse_conntrack_size("") == (None, None)


FW4 = (
    "table inet fw4 { # handle 1\n"
    "\tct helper sip { # handle 36\n"
    '\t\ttype "sip" protocol udp\n'
    "\t}\n"
    "\tchain helper_lan { # handle 44\n"
    '\t\tudp dport 5060 ct helper set "sip" comment "!fw4: SIP VoIP connection tracking" # handle 1089\n'
    "\t}\n"
    "}\n"
)


def test_sip_alg() -> None:
    assert parse_sip_alg(FW4) == SipAlg(state="on", zones=["lan"], ports=[5060])
    two = FW4.replace(
        "}\n}\n",
        '}\n\tchain helper_guest {\n\t\tudp dport 5060 ct helper set "sip" # handle 9\n\t}\n}\n',
    )
    assert parse_sip_alg(two) == SipAlg(state="on", zones=["guest", "lan"], ports=[5060])
    ftp_only = FW4.replace('udp dport 5060 ct helper set "sip"', 'tcp dport 21 ct helper set "ftp"')
    assert parse_sip_alg(ftp_only) == SipAlg(state="off", zones=[], ports=[])
    assert parse_sip_alg("table inet other {\n}\n") == SipAlg(state="unknown", zones=[], ports=[])


def test_new_reads_are_read_only() -> None:
    assert is_read_only_command(CONNTRACK_SIZE)
    assert is_read_only_command(NFT_TEXT)
