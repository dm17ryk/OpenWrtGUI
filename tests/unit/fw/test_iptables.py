"""LuCI's iptables view (v1.0a2 D6): the listing commands and LuCI's parse of their output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.fw.iptables import listing, parse_listing, reset_proven, skipped_lines

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


HEAD = "num      pkts      bytes target     prot opt in     out     source               destination"


def _listing(policy_bytes: int, rule_bytes: int) -> str:
    return (
        f"Chain INPUT (policy ACCEPT 1 packets, {policy_bytes} bytes)\n{HEAD}\n"
        f"1        3 {rule_bytes:>10} DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0"
        "            tcp dpt:22\n"
    )


def test_a_second_reset_with_traffic_between_is_still_proven() -> None:
    """v1.0a2 minor, v1.0b2 D4: counters only grow between resets, so one that went down proves the reset."""
    before = _listing(policy_bytes=120, rule_bytes=60)
    assert reset_proven(before, _listing(policy_bytes=900, rule_bytes=0))  # more traffic since, one lower
    assert not reset_proven(before, _listing(policy_bytes=130, rule_bytes=70))  # every counter grew: no reset
    assert reset_proven(_listing(0, 0), _listing(5, 5))  # nothing counted before: nothing to prove


def test_lines_the_parser_cannot_read_are_counted() -> None:
    text = _listing(10, 10) + "1  2  3  something iptables printed that the app does not know\n\n"
    assert skipped_lines(text) == 1
    assert skipped_lines(_listing(10, 10)) == 0
