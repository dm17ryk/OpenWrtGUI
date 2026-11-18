"""LuCI's iptables view (v1.0a2 D6): the listing commands and LuCI's parse of their output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.fw.iptables import (
    IPT_STATE,
    MARK,
    IptablesPresence,
    listing,
    parse_listing,
    reset_proven,
    skipped_lines,
    split_state,
)
from openwrtgui.guard.readonly import is_read_only_command

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


def test_a_warning_iptables_prints_is_not_a_line_the_app_cannot_read() -> None:
    """The final review: the one-command read folds stderr into a table's text; iptables-nft's warning line
    must not show as "1 line not shown" on every table."""
    warning = "# Warning: iptables-legacy tables present, use iptables-legacy to see them\n"
    assert skipped_lines(warning + _listing(10, 10)) == 0


def test_a_counter_missing_afterwards_proves_nothing() -> None:
    """v1.0b2 deferred minor: a listing that lost the rule (or failed) is no proof of a reset."""
    before = _listing(policy_bytes=0, rule_bytes=500)
    assert reset_proven(before, "") is False  # the after-listing came back empty
    assert reset_proven(before, _listing(policy_bytes=0, rule_bytes=0)) is True


RAW_FAILED = "iptables v1.8.10 (legacy): can't initialize iptables table `raw': Table does not exist\n"


def _section(program: str, table: str, text: str, status: int = 0) -> str:
    return f"{MARK} {program} {table}\n{text}{MARK} exit {status}\n"


def _state_text(raw_status: int = 0) -> str:
    """iptables present with its four tables (raw may fail); ip6tables absent, its tables not found."""
    parts = [f"{MARK} iptables present\n"]
    for table in ("filter", "nat", "mangle"):
        parts.append(_section("iptables", table, LATER["iptables"][table]))
    raw_text = LATER["iptables"]["raw"] if raw_status == 0 else RAW_FAILED
    parts.append(_section("iptables", "raw", raw_text, raw_status))
    parts.append(f"{MARK} ip6tables absent\n")
    for table in ("filter", "nat", "mangle", "raw"):
        parts.append(_section("ip6tables", table, "sh: ip6tables: not found\n", 127))
    return "".join(parts)


def test_the_state_splits_per_program_and_table() -> None:
    """v1.0c Task 3: one command answers every table; presence and each table's exit come back with it."""
    presence, tables, _ = split_state(_state_text())
    assert presence == IptablesPresence(iptables=True, ip6tables=False)
    assert tables[("iptables", "filter")] == (0, LATER["iptables"]["filter"])
    assert tables[("ip6tables", "filter")][0] == 127


def test_a_table_that_fails_keeps_its_error_and_the_others_show() -> None:
    _, tables, _ = split_state(_state_text(raw_status=1))
    assert tables[("iptables", "raw")] == (1, RAW_FAILED)
    assert tables[("iptables", "filter")][0] == 0


def test_a_cut_off_answer_names_no_table_it_did_not_finish() -> None:
    text = _state_text()
    _, tables, _ = split_state(text[: text.index(f"{MARK} iptables nat") + 40])
    assert ("iptables", "filter") in tables and ("iptables", "nat") not in tables


def test_an_empty_or_cut_answer_says_which_programs_answered() -> None:
    """#77 minor 6: no presence line is no answer, not "absent"."""
    assert split_state("")[2] == frozenset()
    text = _state_text()
    assert split_state(text[: text.index(f"{MARK} ip6tables absent")])[2] == frozenset({"iptables"})
    assert split_state(text)[2] == frozenset({"iptables", "ip6tables"})


def test_the_state_read_is_one_read_only_command() -> None:
    assert is_read_only_command(IPT_STATE)
    for program in ("iptables", "ip6tables"):
        for table in ("filter", "nat", "mangle", "raw"):
            assert listing(program, table) in IPT_STATE  # LuCI's own listing, unchanged
