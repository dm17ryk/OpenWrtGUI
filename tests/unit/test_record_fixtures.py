"""tools/record_fixtures.py: the command sets it records and what it hides (no router involved)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from openwrtgui.transport.base import CommandResult

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "record_fixtures.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


rf = _load()

IW_DEV = """phy#0
\tInterface phy0-ap0
\t\tifindex 12
\t\taddr 02:00:00:00:00:02
\t\ttype AP
"""
STATIONS = """Station f4:12:fa:f3:57:68 (on phy0-ap0)
\tinactive time:\t40 ms
Station 3c:84:6a:11:22:33 (on phy0-ap0)
\tinactive time:\t900 ms
"""


class Replay:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, self.answers.get(command, ""), "", 0)


def test_wifi_parked_set_is_exactly_the_planned_commands() -> None:
    assert rf.SETS["wifi-parked"] == (
        "uci -q show wireless",
        'ubus call iwinfo freqlist \'{"device":"radio0"}\'',
        'ubus call iwinfo txpowerlist \'{"device":"radio0"}\'',
        'ubus call iwinfo countrylist \'{"device":"radio0"}\'',
        "iw phy phy0 info",
        "iw dev",
        "uci show",
    )


def test_uci_show_secrets_are_hidden() -> None:
    text = (
        "wireless.default_radio0.ssid='OpenWrt'\n"
        "wireless.default_radio0.key='lab key with $pace'\n"
        "network.wan.password='ppp-secret'\n"
        "rpcd.@login[0].password='$p$root'\n"
    )
    out = rf.sanitize(text)
    assert "lab key" not in out and "ppp-secret" not in out and "$p$root" not in out
    assert "wireless.default_radio0.key='<hidden>'" in out and "ssid='OpenWrt'" in out


def test_json_secrets_and_imei_are_hidden() -> None:
    out = rf.sanitize('{"key": "abc", "imei": "356938035643809"}')
    assert '"key": "<hidden>"' in out and "356938035643809" not in out


async def test_wifi_on_commands_follow_the_ap_interface_and_its_stations() -> None:
    t = Replay({"iw dev": IW_DEV, "iw dev phy0-ap0 station dump": STATIONS})
    commands = await rf.wifi_on_commands(t)
    assert commands[:6] == (
        "iw dev phy0-ap0 info",
        "iw dev phy0-ap0 station dump",
        "iw dev phy0-ap0 survey dump",
        "cat /sys/kernel/debug/ieee80211/phy0/statistics/dot11ACKFailureCount",
        "iw phy phy0 info",
        "ubus -v list 'hostapd.*'",
    )
    assert commands[6:] == tuple(
        f"cat /sys/kernel/debug/ieee80211/phy0/netdev:phy0-ap0/stations/{mac}/rc_stats_csv"
        for mac in ("f4:12:fa:f3:57:68", "3c:84:6a:11:22:33")
    )


async def test_wifi_on_needs_a_radio_on_air() -> None:
    t = Replay({"iw dev": "phy#0\n"})
    try:
        await rf.wifi_on_commands(t)
    except RuntimeError as exc:
        assert "no AP interface on phy0" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


async def test_recording_sanitizes_each_answer() -> None:
    t = Replay({"uci show": "wireless.default_radio0.key='k'\n"})
    recorded = await rf.run_set(t, ("uci show",))
    assert recorded == {"uci show": {"stdout": "wireless.default_radio0.key='<hidden>'\n", "exit": 0}}


def test_out_path_per_set() -> None:
    assert rf.out_file(Path("tests/fixtures/ap2"), "probe") == Path("tests/fixtures/ap2/commands.json")
    assert rf.out_file(Path("tests/fixtures/ap2"), "wifi-parked") == Path(
        "tests/fixtures/ap2/wifi_parked.json"
    )
    assert rf.out_file(Path("x/wifi_on.json"), "wifi-on") == Path("x/wifi_on.json")


def test_refuses_other_hosts() -> None:
    assert rf.main(["--host", "192.168.1.1", "--identity", "k", "--out", "x", "--set", "wifi-parked"]) == 2
