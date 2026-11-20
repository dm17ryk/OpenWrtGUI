"""Station management (v1.2b R8-R10) over hostapd's ubus: BSS transition request (802.11v), neighbour report
and beacon report request (802.11k). A request that expects the station's answer listens 10 s first with
`ubus subscribe` on its own connection; the neighbour list is runtime only."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.ifname import checked_ifname
from openwrtgui.probe.ubus_list import parse_ubus_list
from openwrtgui.transport.base import ubus_command

METHODS = ("bss_transition_request", "rrm_nr_get_own", "rrm_nr_list", "rrm_nr_set", "rrm_beacon_req")
HOSTAPD_LIST = "ubus -v list 'hostapd.*'"
LISTEN_S = 10
LISTEN_KILL_S = 12
WILDCARD_BSSID = "ff:ff:ff:ff:ff:ff"
BEACON_MODE_ACTIVE = 1
BEACON_DURATION_TU = 100
VALIDITY_TBTT = 100
RUNTIME = "Kept until the next Wi-Fi reload: hostapd does not save it."
NO_ANSWER = "No answer from the station in 10 s."
MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
_NR = re.compile(r"(?:[0-9a-f]{2}){1,255}")
_HOSTAPD = re.compile(r"hostapd\.(.+)")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class NeighbourEntry(_Frozen):
    bssid: str
    ssid: str
    nr: str  # hex
    source: str  # the router's name and the AP's SSID


class StationRow(_Frozen):
    mac: str
    name: str | None
    ip: str | None
    signal_dbm: int | None


class ApStations(_Frozen):
    ifname: str
    ssid: str
    channel: int | None
    methods: list[str]
    own: NeighbourEntry | None
    neighbours: list[NeighbourEntry]
    stations: list[StationRow]


class StationsView(_Frozen):
    aps: list[ApStations]
    candidates: list[NeighbourEntry]
    notes: list[str]


class StationAction(BaseModel):
    kind: Literal["transition", "beacon", "neighbours"]
    ifname: str
    mac: str | None = None
    target: str | None = None  # a candidate's bssid
    neighbours: list[str] = []  # candidate bssids; [] clears


class StationApply(StationAction):
    digest: str


class HostapdEvent(_Frozen):
    type: str
    fields: dict[str, str | int | float | bool | None]


class BeaconRow(_Frozen):
    bssid: str | None
    channel: int | None
    rcpi_dbm: float | None  # RCPI / 2 - 110
    rsni: int | None

    @classmethod
    def of(cls, event: HostapdEvent) -> BeaconRow:
        f = event.fields
        rcpi = f.get("rcpi")
        channel, rsni, bssid = f.get("channel"), f.get("rsni"), f.get("bssid")
        return cls(
            bssid=str(bssid).lower() if isinstance(bssid, str) else None,
            channel=channel if isinstance(channel, int) and not isinstance(channel, bool) else None,
            rcpi_dbm=float(rcpi) / 2 - 110
            if isinstance(rcpi, int | float) and not isinstance(rcpi, bool)
            else None,
            rsni=rsni if isinstance(rsni, int) and not isinstance(rsni, bool) else None,
        )


class ActionResult(_Frozen):
    ok: bool
    detail: str
    events: list[HostapdEvent]
    beacons: list[BeaconRow]
    status_code: int | None


def op_class(channel: int) -> int:
    """The global operating class of a 20 MHz channel (IEEE 802.11 Annex E)."""
    for low, high, klass in (
        (1, 13, 81),
        (14, 14, 82),
        (36, 48, 115),
        (52, 64, 118),
        (100, 144, 121),
        (149, 177, 125),
    ):
        if low <= channel <= high:
            return klass
    raise ValueError(f"Channel {channel} has no operating class this app knows")


def checked_mac(mac: str) -> str:
    mac = mac.strip().lower()
    if not MAC.fullmatch(mac):
        raise ValueError(f"{mac!r} is not a MAC address")
    return mac


def hostapd_methods(text: str) -> dict[str, list[str]]:
    """From `ubus -v list 'hostapd.*'`: each AP interface and which of METHODS its hostapd has."""
    out: dict[str, list[str]] = {}
    for obj, methods in parse_ubus_list(text).items():
        if m := _HOSTAPD.fullmatch(obj):
            out[m.group(1)] = [name for name in METHODS if name in methods]
    return out


def neighbour_entry(value: Any, source: str) -> NeighbourEntry | None:
    """One `[bssid, ssid, nr]` from hostapd, checked: a bad one is left out (it would reach a command)."""
    if not isinstance(value, list) or len(value) != 3 or not all(isinstance(v, str) for v in value):
        return None
    bssid, ssid, nr = value[0].lower(), value[1], value[2].lower()
    if not MAC.fullmatch(bssid) or not 1 <= len(ssid) <= 32 or not _NR.fullmatch(nr):
        return None
    return NeighbourEntry(bssid=bssid, ssid=ssid, nr=nr, source=source)


def _hostapd(ifname: str) -> str:
    return f"hostapd.{checked_ifname(ifname)}"


def neighbours_set_command(ifname: str, entries: Sequence[Sequence[str]]) -> str:
    return ubus_command(_hostapd(ifname), "rrm_nr_set", {"list": [list(e) for e in entries]})


def transition_command(ifname: str, mac: str, nr: str) -> str:
    args = {
        "addr": checked_mac(mac),
        "disassociation_imminent": False,
        "disassociation_timer": 0,
        "validity_period": VALIDITY_TBTT,
        "abridged": True,
        "neighbors": [nr],
    }
    return ubus_command(_hostapd(ifname), "bss_transition_request", args)


def beacon_request_command(ifname: str, mac: str, channel: int) -> str:
    args = {
        "addr": checked_mac(mac),
        "mode": BEACON_MODE_ACTIVE,
        "op_class": op_class(channel),
        "channel": channel,
        "duration": BEACON_DURATION_TU,
        "bssid": WILDCARD_BSSID,
    }
    return ubus_command(_hostapd(ifname), "rrm_beacon_req", args)


def listen_command(ifname: str) -> str:
    return f"timeout -s KILL {LISTEN_KILL_S} ubus subscribe {_hostapd(ifname)}"


def parse_event(line: str) -> HostapdEvent | None:
    """One `ubus subscribe` line, `{ "<type>": {…} }`; None for anything else."""
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict) or len(obj) != 1:
        return None
    ((kind, data),) = obj.items()
    if not isinstance(data, dict):
        return None
    fields = {str(k): v for k, v in data.items() if v is None or isinstance(v, str | int | float | bool)}
    return HostapdEvent(type=str(kind), fields=fields)


def not_supported(router: str, kind: str) -> str:
    if kind == "transition":
        what, option = "BSS transition", "bss_transition"
    elif kind == "beacon":
        what, option = "The beacon report", "ieee80211k"
    else:
        what, option = "The neighbour report", "ieee80211k"
    return (
        f"hostapd on {router} says Not supported. {what} needs {option} on this SSID: "
        f"Wi-Fi › All options › {option}."
    )


def no_method(method: str) -> str:
    return f"This router's hostapd has no {method}: it needs a full wpad build."


def gone(mac: str, ssid: str) -> str:
    return f"{mac} is no longer connected to {ssid}."
