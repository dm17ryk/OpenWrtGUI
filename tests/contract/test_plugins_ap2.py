"""System › Plugins on AP2's recording (v1.0a2 D8): luci_plugins has only `global`; no plugins installed."""

from __future__ import annotations

from pathlib import Path

from openwrtgui.system.plugins import plugin_state
from openwrtgui.transport.fake import load_commands
from openwrtgui.uci import parse_uci_show

RECORDING = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "discovery.json"


def test_ap2_shows_the_switches_and_no_plugins() -> None:
    uci = parse_uci_show(load_commands(RECORDING)["uci show luci_plugins"].stdout)
    state = plugin_state(uci, [])
    assert (state.enabled, state.global_section, state.groups, state.plugins) == (False, True, [], [])
