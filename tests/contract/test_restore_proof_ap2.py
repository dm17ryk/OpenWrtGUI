"""The restore's config proof replayed against AP2's recorded `uci -X show` outputs (AGENTS.md: command
strings live in the catalog and are replayed by contract tests).

Each recorded config is written back as the backup would hold it (named sections by name, libuci's
cfgXXXXXX as unnamed ones, one word an option, several a list), and the proof must read AP2's own answer as
holding it. AP2's recordings hold no failed `uci` read, so a config that does not read is covered by the unit
tests only (uci answers "Entry not found" with a non-zero exit, and any failed read counts as missing).
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

from openwrtgui.system import commands as s
from openwrtgui.system.restore import differing
from openwrtgui.transport.base import CommandResult
from openwrtgui.transport.fake import ReplayTransport

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ap2"
RECORDED = {
    "system": "system.json",
    "dropbear": "access.json",
    "uhttpd": "access.json",
    "rpcd": "access.json",
    "network": "network.json",
    "dhcp": "network.json",
    "firewall": "firewall.json",
}
_LIBUCI = re.compile(r"cfg[0-9a-f]{6}")


def _recorded(config: str) -> str:
    entry = json.loads((FIXTURES / RECORDED[config]).read_text("utf-8"))[s.uci_show_config(config)]
    assert entry["exit"] == 0, entry
    return str(entry["stdout"])


def _as_file(shown: str) -> str:
    """`uci -X show` output as /etc/config/<config> holds it."""
    lines: list[str] = []
    for raw in shown.splitlines():
        path, _, value = raw.partition("=")
        parts = path.split(".")
        words = shlex.split(value)
        if len(parts) == 2:
            lines.append(f"config {words[0]}" + ("" if _LIBUCI.fullmatch(parts[1]) else f" '{parts[1]}'"))
        elif len(words) == 1:
            lines.append(f"\toption {parts[2]} {shlex.quote(words[0])}")
        else:
            lines += [f"\tlist {parts[2]} {shlex.quote(w)}" for w in words]
    return "\n".join(lines) + "\n"


def _router(config: str, shown: str) -> ReplayTransport:
    return ReplayTransport(
        {s.uci_show_config(config): CommandResult(s.uci_show_config(config), shown, "", 0)}
    )


@pytest.mark.parametrize("config", sorted(RECORDED))
async def test_ap2s_own_config_holds_its_backup(config: str) -> None:
    shown = _recorded(config)
    assert await differing(_router(config, shown), [], ((config, _as_file(shown)),)) == []


async def test_a_changed_option_in_ap2s_system_differs() -> None:
    shown = _recorded("system")
    backup = re.sub(r"(option hostname )\S+", r"\1not-ap2", _as_file(shown))
    assert "not-ap2" in backup
    assert await differing(_router("system", shown), [], (("system", backup),)) == ["/etc/config/system"]


async def test_ap2s_uhttpd_lists_hold_in_any_order_but_not_with_an_item_missing() -> None:
    shown = _recorded("uhttpd")
    lists = [line for line in shown.splitlines() if len(shlex.split(line.partition("=")[2])) > 1]
    assert lists, "AP2's uhttpd has a list (listen_http)"
    path, _, value = lists[0].partition("=")
    words = shlex.split(value)
    backup = _as_file(shown)
    reordered = shown.replace(lists[0], f"{path}=" + " ".join(shlex.quote(w) for w in reversed(words)))
    assert await differing(_router("uhttpd", reordered), [], (("uhttpd", backup),)) == []
    shorter = shown.replace(lists[0], f"{path}=" + " ".join(shlex.quote(w) for w in words[1:]))
    assert await differing(_router("uhttpd", shorter), [], (("uhttpd", backup),)) == ["/etc/config/uhttpd"]
