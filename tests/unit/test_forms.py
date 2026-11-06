"""Typed-option rows and edits for any config (the "All options" editors)."""

from __future__ import annotations

import pytest

from openwrtgui.forms import OptionEdit, compile_edits, option_rows
from openwrtgui.uci import UciOp

VALIDATE = {"interface": {"ipaddr": "list(ipaddr)", "mtu": "uinteger", "password": "string"}}


def test_option_rows_for_another_config() -> None:
    rows = option_rows(
        "network",
        [("interface", "lan")],
        {"interface": {"ipaddr": "list(ipaddr)", "mtu": "uinteger"}},
        {"network.lan.mtu": "1500"},
        controlled={"interface": {"ipaddr": "Address"}},
    )
    assert [(r.config, r.name, r.editor, r.control) for r in rows] == [
        ("network", "ipaddr", "list", "Address"),
        ("network", "mtu", "number", None),
    ]
    assert rows[1].value == "1500" and rows[1].set_in_config


def test_secret_values_are_never_read_back() -> None:
    rows = option_rows("network", [("interface", "wan")], VALIDATE, {"network.wan.password": "s3cret"})
    secret = next(r for r in rows if r.name == "password")
    assert secret.editor == "secret" and secret.value is None and secret.set_in_config


def test_compile_edits_targets_the_config() -> None:
    rows = option_rows("network", [("interface", "wan")], VALIDATE, {})
    ops, secrets = compile_edits(
        "network",
        [
            OptionEdit("wan", "mtu", "1400"),
            OptionEdit("wan", "password", "p'w"),
            OptionEdit("wan", "ipaddr", None),
        ],
        rows,
    )
    assert ops == [
        UciOp("set", "network.wan.mtu", "1400"),
        UciOp("set", "network.wan.password", "p'w"),
        UciOp("delete", "network.wan.ipaddr"),
    ]
    assert secrets == ["p'w"]


def test_writer_and_read_only_hooks() -> None:
    rows = option_rows(
        "network",
        [("interface", "wan")],
        VALIDATE,
        {},
        read_only=frozenset({"mtu"}),
        writer_of=lambda group, name: "harness" if name == "ipaddr" else None,
    )
    by_name = {r.name: r for r in rows}
    assert by_name["mtu"].editor == "readonly" and by_name["ipaddr"].writer == "harness"
    with pytest.raises(ValueError, match="mtu is read-only"):
        compile_edits("network", [OptionEdit("wan", "mtu", "1")], rows)


def test_controlled_row_refused() -> None:
    """#26: an option with its own control is changed there, never as a plain row (which would skip the
    control's checks, e.g. the address prefix rule and the address follow)."""
    rows = option_rows(
        "network",
        [("interface", "lan")],
        {"interface": {"ipaddr": "list(ipaddr)"}},
        {},
        controlled={"interface": {"ipaddr": "Address"}},
    )
    with pytest.raises(ValueError, match=r"^ipaddr has its own control \(Address\); change it there\.$"):
        compile_edits("network", [OptionEdit("lan", "ipaddr", ["10.0.0.1/24"])], rows)
