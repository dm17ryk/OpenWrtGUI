"""Offline: parking AP2 after a window (HW-2, 2026-11-13: after the owgmon0 test the AP interface was still up
20 s after `wifi down radio0; wifi up radio0`). The park says what netifd thinks, never AP2's key, and takes
radio0 down and up once more."""

from __future__ import annotations

import json
from typing import cast

import pytest
from test_ap2_wifi_faults import _park

from openwrtgui.transport.base import CommandResult, Transport

IW_AP = "phy#0\n\tInterface phy0-ap0\n\t\tifindex 12\n\t\ttype AP\n"
STATUS = json.dumps(
    {
        "radio0": {
            "up": True,
            "pending": False,
            "autostart": True,
            "disabled": True,
            "interfaces": [{"ifname": "phy0-ap0", "config": {"ssid": "OwgTest", "key": "not-for-the-log"}}],
        }
    }
)


class _Radio:
    """The AP interface goes only after `stays` + 1 `wifi down` commands."""

    def __init__(self, stays: int) -> None:
        self.stays = stays
        self.downs = 0
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        if command.startswith("wifi down radio0"):
            self.downs += 1
        if command == "iw dev":
            return CommandResult(command, IW_AP if self.downs <= self.stays else "", "", 0)
        if command == "ubus call network.wireless status":
            return CommandResult(command, STATUS, "", 0)
        return CommandResult(command, "", "", 0)


async def _no_sleep(_: float) -> None:
    return None


async def test_a_radio_that_parks_takes_one_pass() -> None:
    radio = _Radio(stays=0)
    assert await _park(cast(Transport, radio), waits=3, sleep=_no_sleep) == 1
    assert radio.calls.count("ubus call network.wireless status") == 0


async def test_an_ap_that_stays_gets_one_more_pass_and_netifd_is_shown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    radio = _Radio(stays=1)
    assert await _park(cast(Transport, radio), waits=3, sleep=_no_sleep) == 2
    assert "wifi down radio0" in radio.calls and "wifi up radio0" in radio.calls
    shown = capsys.readouterr().out
    assert "still on air" in shown and "phy0-ap0" in shown and "'up': True" in shown
    assert "not-for-the-log" not in shown and "OwgTest" not in shown


async def test_an_ap_that_never_goes_is_reported() -> None:
    assert await _park(cast(Transport, _Radio(stays=9)), waits=3, sleep=_no_sleep) == 0
