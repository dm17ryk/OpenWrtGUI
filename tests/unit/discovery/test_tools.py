"""discovery/tools.py: promoted tool cards (checks, prefill from usage, exact commands) and their store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openwrtgui.discovery.tools import (
    ToolCard,
    ToolCommand,
    ToolParam,
    ToolStore,
    check_card,
    help_command,
    prefill_card,
    tool_command,
)

BOARD = "dlink,dwr-921-c3-uboot"
USAGE = "Usage: dwr921-portctl {port-status|port-enable|port-disable} {lan1|lan2|lan3|lan4|wan}"
PORT = ToolParam(name="arg1", kind="choice", choices=("lan1", "lan2", "lan3", "lan4", "wan"))
CARD = ToolCard(
    board=BOARD,
    path="/usr/sbin/dwr921-portctl",
    name="dwr921-portctl",
    commands=(
        ToolCommand(label="port-status", args=("port-status", "{arg1}"), params=(PORT,), write=False),
        ToolCommand(label="port-enable", args=("port-enable", "{arg1}"), params=(PORT,), write=True),
    ),
)


def test_prefill_from_portctl_usage() -> None:
    card = prefill_card(BOARD, "/usr/sbin/dwr921-portctl", USAGE)
    assert card.name == "dwr921-portctl"
    assert [c.label for c in card.commands] == ["port-status", "port-enable", "port-disable"]
    assert card.commands[1].args == ("port-enable", "{arg1}")
    assert card.commands[1].params == (PORT,)
    assert all(c.write for c in card.commands)  # unknown: a write until the user marks a command read-only
    check_card(card)


def test_prefill_without_usage() -> None:
    card = prefill_card(BOARD, "/usr/sbin/wifi-mirror", None)
    assert [(c.label, c.args, c.write) for c in card.commands] == [("run", (), True)]
    optional = prefill_card(BOARD, "/usr/bin/x", "Usage: x [-v] {start|stop}")
    assert [c.args for c in optional.commands] == [("start",), ("stop",)]


def test_prefill_reads_brackets_and_braces_as_the_usage_line_means() -> None:
    nested = prefill_card(BOARD, "/usr/bin/x", "Usage: x [-o [file]] {a|b} [--] {lan1|wan} {unclosed")
    assert [c.args for c in nested.commands] == [("a", "{arg1}"), ("b", "{arg1}")]
    assert nested.commands[0].params[0].choices == ("lan1", "wan")
    unclosed = prefill_card(BOARD, "/usr/bin/x", "Usage: x [-v {start|stop}")
    assert [c.args for c in unclosed.commands] == [("start",), ("stop",)]


@pytest.mark.parametrize("usage", ["Usage: x " + "[" * 200_000, "Usage: x " + "{{|" * 70_000])
def test_prefill_reads_a_hostile_usage_line_in_linear_time(usage: str) -> None:
    """CodeQL py/polynomial-redos: a long run of '[' or '{{|' must not make the prefill quadratic."""
    started = time.monotonic()
    card = prefill_card(BOARD, "/usr/bin/x", usage)
    assert time.monotonic() - started < 0.5
    assert [c.label for c in card.commands] == ["run"]


def test_tool_command_quotes_and_checks() -> None:
    assert tool_command(CARD, "port-enable", {"arg1": "lan2"}) == "/usr/sbin/dwr921-portctl port-enable lan2"
    with pytest.raises(ValueError, match=r"^arg1 must be one of lan1, lan2, lan3, lan4, wan$"):
        tool_command(CARD, "port-enable", {"arg1": "lan2; reboot"})
    with pytest.raises(ValueError, match=r"^arg1 needs a value$"):
        tool_command(CARD, "port-enable", {})
    with pytest.raises(ValueError, match=r"^dwr921-portctl has no command reboot$"):
        tool_command(CARD, "reboot", {})


def test_text_and_number_params() -> None:
    card = CARD.model_copy(
        update={
            "commands": (
                ToolCommand(
                    label="probe",
                    args=("--host", "{host}", "--count", "{n}"),
                    params=(
                        ToolParam(name="host", kind="text"),
                        ToolParam(name="n", kind="number", minimum=1, maximum=9),
                    ),
                    write=False,
                ),
            )
        }
    )
    assert tool_command(card, "probe", {"host": "192.168.1.30", "n": "3"}) == (
        "/usr/sbin/dwr921-portctl --host 192.168.1.30 --count 3"
    )
    with pytest.raises(ValueError, match=r"^host must match "):
        tool_command(card, "probe", {"host": "a b", "n": "3"})
    with pytest.raises(ValueError, match=r"^n is a number from 1 to 9$"):
        tool_command(card, "probe", {"host": "x", "n": "10"})


def test_help_command() -> None:
    assert (
        help_command("/usr/sbin/wifi-mirror") == "timeout 5 /usr/sbin/wifi-mirror --help 2>&1 | head -c 8192"
    )
    with pytest.raises(ValueError, match=r"^/usr/sbin/x y is not a program path$"):
        help_command("/usr/sbin/x y")


def test_card_limits() -> None:
    with pytest.raises(ValueError, match=r"^A card name is 1 to 40 characters$"):
        check_card(CARD.model_copy(update={"name": "x" * 41}))
    with pytest.raises(ValueError, match=r"^A card has 1 to 12 commands$"):
        check_card(CARD.model_copy(update={"commands": CARD.commands[:1] * 13}))
    bad = ToolCommand(label="x", args=("a;b",), write=True)
    with pytest.raises(ValueError, match=r"^a;b is not a literal"):
        check_card(CARD.model_copy(update={"commands": (bad,)}))
    undefined = ToolCommand(label="x", args=("{nope}",), write=True)
    with pytest.raises(ValueError, match=r"^\{nope\} is not a parameter of x$"):
        check_card(CARD.model_copy(update={"commands": (undefined,)}))
    broken = ToolCommand(
        label="x", args=("{t}",), params=(ToolParam(name="t", kind="text", pattern="("),), write=True
    )
    with pytest.raises(ValueError, match=r"^\( is not a valid pattern$"):
        check_card(CARD.model_copy(update={"commands": (broken,)}))


def test_store_per_board(tmp_path: Path) -> None:
    store = ToolStore(tmp_path)
    store.save(CARD)
    assert store.cards(BOARD) == [CARD]
    renamed = CARD.model_copy(update={"name": "ports"})
    store.save(renamed)
    assert store.cards(BOARD) == [renamed]
    assert (tmp_path / "dlink,dwr-921-c3-uboot.json").is_file()
    store.delete(BOARD, CARD.path)
    assert store.cards(BOARD) == []
    assert store.cards("other,board") == []
