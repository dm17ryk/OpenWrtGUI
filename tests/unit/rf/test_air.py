"""The command builders of the v0.7 air helpers: scans, the monitor window, and what Bench Guard allows."""

from __future__ import annotations

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.rf.air import (
    FRAME_WINDOW,
    MONITOR_FLAGS,
    SCAN_DEL,
    checked_ifname,
    get_clients,
    scan_add,
    scan_command,
    survey_command,
)


def test_air_writes_are_not_read_only() -> None:
    writes = [
        scan_add("phy0"),
        scan_command("phy0-ap0", on_ap=True),
        scan_command("owgscan0", on_ap=False),
        SCAN_DEL,
        MONITOR_FLAGS,
        FRAME_WINDOW,
        "iw dev owgmon0 set channel 6",
    ]
    for command in writes:
        assert not is_read_only_command(command), command


def test_survey_is_read_only() -> None:
    assert is_read_only_command(survey_command("phy0-ap0"))


def test_command_texts() -> None:
    assert scan_add("phy0") == (
        "iw dev owgscan0 del 2>/dev/null; "
        "iw phy phy0 interface add owgscan0 type managed && ip link set owgscan0 up"
    )
    assert scan_command("phy0-ap0", on_ap=True) == "iw dev phy0-ap0 scan ap-force passive"
    assert scan_command("owgscan0", on_ap=False) == "iw dev owgscan0 scan passive"
    assert survey_command("owgscan0") == "iw dev owgscan0 survey dump"
    assert SCAN_DEL == "iw dev owgscan0 del"
    assert MONITOR_FLAGS == "iw dev owgmon0 set monitor fcsfail control otherbss"
    assert FRAME_WINDOW == "timeout 3 tcpdump -i owgmon0 -e -n -l -v -s 128 -c 2000"
    assert get_clients("phy0-ap0") == "ubus call hostapd.phy0-ap0 get_clients"


def test_ifname_rule() -> None:
    assert checked_ifname("phy0-ap0") == "phy0-ap0"
    assert checked_ifname("owgscan0") == "owgscan0"
    for bad in ("a;b", "x y", "", "a" * 16):
        with pytest.raises(ValueError, match="is not an interface name"):
            checked_ifname(bad)
    with pytest.raises(ValueError):
        scan_command("a;reboot", on_ap=False)
