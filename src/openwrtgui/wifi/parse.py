"""Parsers for what the router prints about Wi-Fi: `uci show`, `iw`, iwinfo results, beacon captures."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_CHANNEL = re.compile(r"channel (\d+) \((\d+) MHz\)(?:, width: (\d+) MHz( \(no HT\))?)?")
_MCS = re.compile(r"HT TX/RX MCS rate indexes supported:\s*(.+)")
# The rate right after the timestamp. A radio's own beacons (TX path) have no "<freq> MHz" after it.
_BEACON_RATE = re.compile(r"\S+ (\d+(?:\.\d+)?) Mb/s ")


@dataclass(frozen=True)
class IwDevInfo:
    ifname: str
    ifindex: int | None
    addr: str | None
    ssid: str | None
    type: str | None
    phy: int | None
    channel: int | None
    freq_mhz: int | None
    width_mhz: int | None
    no_ht: bool
    txpower_dbm: float | None


@dataclass(frozen=True)
class IwIface:
    ifname: str
    phy: int
    type: str
    addr: str | None


def parse_uci_show(text: str) -> dict[str, str]:
    """`uci show` lines to {path: value}; a list's items are joined with spaces."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        path, sep, raw = line.partition("=")
        if not sep or not path:
            continue
        try:
            out[path] = " ".join(shlex.split(raw))
        except ValueError:
            out[path] = raw
    return out


def parse_iw_dev_info(text: str) -> IwDevInfo:
    fields: dict[str, Any] = {}
    channel = freq = width = None
    no_ht = False
    for raw in text.splitlines():
        line = raw.strip()
        key, _, rest = line.partition(" ")
        if key == "Interface":
            fields["ifname"] = rest
        elif key in ("ifindex", "wiphy") and rest.isdigit():
            fields[key] = int(rest)
        elif key in ("addr", "ssid", "type"):
            fields[key] = rest
        elif key == "txpower":
            m = re.match(r"([\d.]+) dBm", rest)
            fields["txpower"] = float(m.group(1)) if m else None
        elif key == "channel" and (m := _CHANNEL.match(line)):
            channel, freq = int(m.group(1)), int(m.group(2))
            width = int(m.group(3)) if m.group(3) else None
            no_ht = bool(m.group(4))
    return IwDevInfo(
        ifname=fields.get("ifname", ""),
        ifindex=fields.get("ifindex"),
        addr=fields.get("addr"),
        ssid=fields.get("ssid"),
        type=fields.get("type"),
        phy=fields.get("wiphy"),
        channel=channel,
        freq_mhz=freq,
        width_mhz=width,
        no_ht=no_ht,
        txpower_dbm=fields.get("txpower"),
    )


def parse_iw_dev(text: str) -> list[IwIface]:
    """`iw dev`: every interface with its phy, type and address."""
    out: list[IwIface] = []
    phy: int | None = None
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is not None and phy is not None:
            out.append(IwIface(current["ifname"], phy, current.get("type", ""), current.get("addr")))

    for raw in text.splitlines():
        line = raw.strip()
        if m := re.match(r"phy#(\d+)$", line):
            flush()
            phy, current = int(m.group(1)), None
        elif line.startswith("Interface "):
            flush()
            current = {"ifname": line.split(" ", 1)[1]}
        elif current is not None:
            key, _, rest = line.partition(" ")
            if key in ("type", "addr"):
                current[key] = rest
    flush()
    return out


def parse_ht_mcs(iw_phy_info: str) -> tuple[int, ...]:
    m = _MCS.search(iw_phy_info)
    if m is None:
        return ()
    indexes: list[int] = []
    for part in m.group(1).split(","):
        part = part.strip()
        if "-" in part:
            lo, _, hi = part.partition("-")
            if lo.isdigit() and hi.isdigit():
                indexes.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            indexes.append(int(part))
    return tuple(indexes)


def parse_freqlist(result: Mapping[str, Any]) -> tuple[int, ...]:
    """Channels the radio may use in the current country (`restricted` ones left out)."""
    return tuple(
        int(f["channel"]) for f in result.get("results", []) if "channel" in f and not f.get("restricted")
    )


def parse_txpowerlist(result: Mapping[str, Any]) -> tuple[int, ...]:
    return tuple(int(p["dbm"]) for p in result.get("results", []) if "dbm" in p)


def parse_beacon_rates(tcpdump_text: str) -> list[float]:
    """The rate of every beacon in a `tcpdump -e` capture on a monitor interface."""
    rates = []
    for line in tcpdump_text.splitlines():
        if "Beacon" in line and (m := _BEACON_RATE.match(line)):
            rates.append(float(m.group(1)))
    return rates
