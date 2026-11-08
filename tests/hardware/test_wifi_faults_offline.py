"""The O16 test's own safety helpers, checked offline (no hardware marker): they guard AP2's wireless
config, pick only the test SSID's station and leave the phone's other suggestions alone."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest
from test_ap2_wifi_faults import TEST_SSID, AdbStation, _associated, _station, _test_bss

from conftest import FwWindow, wireless_snapshot
from openwrtgui.faults.model import FaultTarget
from openwrtgui.transport.base import CommandResult, Transport, ubus_command

RADIO = "config wifi-device 'radio0'\n\toption channel '6'\n"
IW_DEV = """phy#0
\tInterface phy0-ap1
\t\tifindex 13
\t\ttype AP
\tInterface phy0-ap0
\t\tifindex 12
\t\ttype AP
"""


class _Router:
    """Answers each command from a table; anything else fails as a missing file would."""

    def __init__(self, answers: dict[str, CommandResult]) -> None:
        self.answers = answers

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return self.answers.get(command, CommandResult(command, "", "not found", 1))


def _ok(command: str, stdout: str) -> CommandResult:
    return CommandResult(command, stdout, "", 0)


async def test_wireless_snapshot_refuses_a_failed_read() -> None:
    t = cast(Transport, _Router({}))
    with pytest.raises(AssertionError, match="cannot read AP2's wireless config"):
        await wireless_snapshot(t)


async def test_wireless_snapshot_refuses_a_file_without_a_radio() -> None:
    t = cast(Transport, _Router({"cat /etc/config/wireless": _ok("cat /etc/config/wireless", "")}))
    with pytest.raises(AssertionError, match="cannot read AP2's wireless config"):
        await wireless_snapshot(t)


async def test_wireless_snapshot_returns_the_file() -> None:
    t = cast(Transport, _Router({"cat /etc/config/wireless": _ok("cat /etc/config/wireless", RADIO)}))
    assert await wireless_snapshot(t) == RADIO


async def test_test_bss_is_the_ap_interface_with_the_test_ssid() -> None:
    t = cast(
        Transport,
        _Router(
            {
                "iw dev": _ok("iw dev", IW_DEV),
                "iw dev phy0-ap1 info": _ok("", "Interface phy0-ap1\n\tssid Other\n\ttype AP\n\twiphy 0\n"),
                "iw dev phy0-ap0 info": _ok(
                    "", f"Interface phy0-ap0\n\tssid {TEST_SSID}\n\ttype AP\n\twiphy 0\n"
                ),
            }
        ),
    )
    assert await _test_bss(t) == "phy0-ap0"


async def test_associated_leaves_out_a_deauthenticated_station() -> None:
    # hostapd keeps a deauthenticated station listed, no longer associated, for about a second (AP2,
    # 2026-11-09: the phone was still listed right after the ban)
    clients = {
        "clients": {
            "02:00:00:00:00:0A": {"auth": True, "assoc": True, "authorized": True},
            "02:00:00:00:00:0b": {"auth": False, "assoc": False, "authorized": False},
        }
    }
    command = ubus_command("hostapd.phy0-ap0", "get_clients")
    t = cast(Transport, _Router({command: _ok(command, json.dumps(clients))}))
    assert await _associated(t, "phy0-ap0") == {"02:00:00:00:00:0a"}


class _Scanner:
    async def scan(self) -> None:
        return None


async def test_station_ignores_clients_of_other_interfaces() -> None:
    phone = FaultTarget(None, "02:00:00:00:00:0b", None, "phy0-ap0", "phy0-ap0")
    targets = (
        FaultTarget(None, "02:00:00:00:00:0a", None, "phy0-ap1", "phy0-ap1"),
        phone,
        FaultTarget(None, "02:00:00:00:00:0c", "192.168.1.10", "wired", "eth0.1"),
    )

    async def state(router_id: str) -> SimpleNamespace:
        return SimpleNamespace(targets=targets)

    w = cast(FwWindow, SimpleNamespace(faults=SimpleNamespace(state=state)))
    assert await _station(w, cast(AdbStation, _Scanner()), "phy0-ap0") == phone


class _Phone(AdbStation):
    """The adb shell, answered from memory: records every `cmd wifi` call."""

    def __init__(self, suggestions: str) -> None:
        super().__init__("serial")
        self.suggestions = suggestions
        self.calls: list[str] = []

    def _shell(self, *args: str, check: bool = True) -> str:
        self.calls.append(args[0])
        if args[0] == "status":
            return "Wifi is enabled\n"
        if args[0] == "list-suggestions":
            return self.suggestions
        return ""


async def test_join_leaves_an_existing_suggestion_alone() -> None:
    phone = _Phone(f'WifiNetworkSuggestion: SSID: "{TEST_SSID}" ...\n')
    with pytest.raises(RuntimeError, match="already has"):
        await phone.join(TEST_SSID, "k")
    await phone.forget(TEST_SSID)
    assert "add-suggestion" not in phone.calls
    assert "remove-suggestion" not in phone.calls


async def test_join_adds_and_forget_removes_its_own_suggestion() -> None:
    phone = _Phone("No suggestions on this device\n")
    await phone.join(TEST_SSID, "k")
    await phone.forget(TEST_SSID)
    assert phone.calls.count("add-suggestion") == 1
    assert phone.calls.count("remove-suggestion") == 1
