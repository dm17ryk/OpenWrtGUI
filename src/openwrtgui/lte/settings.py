"""The LTE settings form (v0.6a plan, "LTE rules") as one v0.3 interface request for network.lte."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.forms import OptionEdit
from openwrtgui.net.interfaces import InterfaceRequest

Auth = Literal["none", "pap", "chap", "both"]
PdpType = Literal["ipv4", "ipv6", "ipv4v6"]
PIN = re.compile(r"[0-9]{4,8}")
PIN_MESSAGE = "A SIM PIN is 4 to 8 digits"
_TEXT = ("apn", "auth", "username", "password", "pdptype")


@dataclass(frozen=True)
class LteSettings:
    """None leaves a field as it is; "" in a text field removes the option (the handler's default applies)."""

    apn: str | None = None
    auth: Auth | None = None
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    pincode: str | None = field(default=None, repr=False)
    pdptype: PdpType | None = None
    mtu: int | None = None
    metric: int | None = None
    auto: bool | None = None
    defaultroute: bool | None = None
    edits: tuple[OptionEdit, ...] = field(default=(), repr=False)


def _named(name: str, s: LteSettings) -> list[OptionEdit]:
    named = [
        OptionEdit(name, option, getattr(s, option) or None)
        for option in _TEXT
        if getattr(s, option) is not None
    ]
    if s.pincode is not None:
        if s.pincode and not PIN.fullmatch(s.pincode):
            raise ValueError(PIN_MESSAGE)
        named.append(OptionEdit(name, "pincode", s.pincode or None))
    if s.metric is not None:
        named.append(OptionEdit(name, "metric", str(s.metric)))
    if s.defaultroute is not None:
        named.append(OptionEdit(name, "defaultroute", "1" if s.defaultroute else "0"))
    return named


def settings_request(name: str, s: LteSettings) -> InterfaceRequest:
    """The named fields become option edits on `name` beside All options' edits; MTU and bring up at boot
    are the interface request's own fields. The caller has checked every edit is on `name`."""
    named = _named(name, s)
    given = {e.name for e in named}
    twice = next((e.name for e in s.edits if e.name in given), None)
    if twice is not None:
        raise ValueError(f"{twice} is given twice")
    return InterfaceRequest(name=name, mtu=s.mtu, auto=s.auto, edits=(*named, *s.edits))
