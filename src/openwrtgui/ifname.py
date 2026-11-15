"""Interface, phy and radio names, checked before they go into a command or a file name (v1.0b1 D5)."""

from __future__ import annotations

import re

# Linux names are at most 15 characters; no space, quote or shell character, and no leading dash (an option)
IFNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,14}")
RADIO = re.compile(r"[A-Za-z0-9_]{1,15}")  # a uci section name: what `wireless.<radio>` can be


def checked_ifname(name: str) -> str:
    if not IFNAME.fullmatch(name):
        raise ValueError(f"{name!r} is not an interface name")
    return name


def checked_radio(name: str) -> str:
    if not RADIO.fullmatch(name):
        raise ValueError(f"{name!r} is not a radio name")
    return name
