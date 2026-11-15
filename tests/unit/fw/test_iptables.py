"""LuCI's iptables view (v1.0a2 D6): the listing commands and LuCI's parse of their output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.fw.iptables import listing, parse_listing

LATER = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "sim" / "later" / "ap4.json").read_text("utf-8")
)


def test_the_listing_commands_are_luci_s() -> None:
    assert listing("iptables", "nat") == "iptables --line-numbers -w -nvxL -t nat"
    with pytest.raises(ValueError):
        listing("iptables", "security")


def test_parse_luci_shapes() -> None:
    chains = parse_listing(LATER["iptables"]["filter"])
    assert [(c.name, c.policy, c.packets, c.references) for c in chains] == [
        ("INPUT", "ACCEPT", 1200, None),
        ("FORWARD", "DROP", 0, None),
        ("OUTPUT", "ACCEPT", 900, None),
        ("lab_user", None, None, 0),
    ]
    first, ssh = chains[0].rules
    got = (first.num, first.packets, first.target, first.inp, first.source, first.options, first.comment)
    assert got == (1, 640, "ACCEPT", "lo", "0.0.0.0/0", "", None)
    assert (ssh.target, ssh.prot, ssh.source, ssh.options, ssh.comment) == (
        "DROP",
        "tcp",
        "10.9.8.0/24",
        "tcp dpt:22",
        "Drop SSH from the lab net",
    )
    (v6,) = parse_listing(LATER["ip6tables"]["filter"])[0].rules
    assert (v6.prot, v6.source, v6.destination) == ("icmpv6", "fe80::/10", "::/0")


def test_a_rule_without_options_or_trailing_spaces_is_kept() -> None:
    text = (
        "Chain X (policy ACCEPT 0 packets, 0 bytes)\n"
        "num pkts bytes target prot opt in out source destination\n"
        "1 0 0 ACCEPT all -- * * 0.0.0.0/0 0.0.0.0/0"
    )
    assert len(parse_listing(text)[0].rules) == 1
