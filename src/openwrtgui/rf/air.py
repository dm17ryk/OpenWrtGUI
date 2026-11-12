"""Commands of the v0.7 air helpers: channel analysis scans and the frame analysis window (plan D12, D13).

A scan and a monitor interface change the radio, so Bench Guard's read-only check refuses them; the survey
dump is a read.
"""

from __future__ import annotations

import re

from openwrtgui.transport.base import ubus_command
from openwrtgui.wifi.monitor import MONITOR

SCAN_IF = "owgscan0"
SCAN_TIMEOUT_S = 30.0
FRAME_WINDOW_S, FRAME_EVERY_S, FRAME_CAP, FRAMES_LIMIT_S = 3, 5, 2000, 1800
IFNAME = re.compile(r"[A-Za-z0-9._-]{1,15}")
RADIO = re.compile(r"[A-Za-z0-9_]{1,15}")


def checked_ifname(name: str) -> str:
    if not IFNAME.fullmatch(name):
        raise ValueError(f"{name!r} is not an interface name")
    return name


def scan_add(phy: str) -> str:
    """A temporary managed interface for a scan on a parked radio; a dropped connection's leftover goes."""
    return (
        f"iw dev {SCAN_IF} del 2>/dev/null; "
        f"iw phy {checked_ifname(phy)} interface add {SCAN_IF} type managed && ip link set {SCAN_IF} up"
    )


SCAN_DEL = f"iw dev {SCAN_IF} del"
SCAN_INFO = f"iw dev {SCAN_IF} info"  # whether the temporary interface is still there


def scan_command(ifname: str, *, on_ap: bool) -> str:
    """A passive scan: nothing is transmitted. On an AP interface mac80211 needs `ap-force`."""
    return f"iw dev {checked_ifname(ifname)} scan {'ap-force ' if on_ap else ''}passive"


def survey_command(ifname: str) -> str:
    return f"iw dev {checked_ifname(ifname)} survey dump"


MONITOR_FLAGS = f"iw dev {MONITOR} set monitor fcsfail control otherbss"
FRAME_WINDOW = f"timeout {FRAME_WINDOW_S} tcpdump -i {MONITOR} -e -n -l -v -s 128 -c {FRAME_CAP}"


def get_clients(ifname: str) -> str:
    return ubus_command(f"hostapd.{checked_ifname(ifname)}", "get_clients", {})
