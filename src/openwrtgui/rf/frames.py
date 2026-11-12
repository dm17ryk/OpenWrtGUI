"""Frame analysis (v0.7 plan D12): `tcpdump -e -v` lines from the monitor interface, summed per window.

The router only prints; the PC parses. A frame's direction comes from its transmitter (address 2): TX from
the AP when one of the radio's BSSIDs sent it, RX at the AP when another station sent it to the BSS. A frame
with a bad FCS counts only in the totals, since its addresses cannot be trusted. The radio's own TX path
carries no signal (spec O4), so the signal histogram is the RX direction's.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

_RATE = re.compile(r"(?<![\d.])(\d+\.\d) Mb/s\b")
_MCS = re.compile(r"\bMCS (\d+)\b")
_SIGNAL = re.compile(r"(-\d+)dBm signal")
_ADDR = re.compile(r"\b(SA|TA|DA|RA|BSSID):([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})(?![:0-9a-fA-F])")
_DROPPED = re.compile(r"(\d+) packets? dropped by kernel")
SIGNAL_BIN_DB = 5


@dataclass(frozen=True)
class Frame:
    rate: str | None  # "MCS 7" when an MCS is printed, else "54.0" (Mb/s), else None
    signal_dbm: int | None  # RX only: the radio's own TX path prints none (O4)
    bad_fcs: bool
    retry: bool
    src: str | None  # the transmitter (address 2)
    bssid: str | None
    dst: str | None  # RA, else DA


@dataclass(frozen=True)
class Direction:
    frames: int = 0
    retries: int = 0
    rates: dict[str, int] = field(default_factory=dict)
    signal_hist: dict[int, int] = field(default_factory=dict)  # bin floor: -50 holds -50 … -46


@dataclass(frozen=True)
class FrameWindow:
    seconds: float
    frames: int  # every frame line heard
    bad_fcs: int
    rx: Direction  # RX at AP
    tx: Direction  # TX from AP
    dropped: int | None


def parse_frame(line: str) -> Frame | None:
    """One tcpdump line; None for the lines tcpdump writes for itself and blank lines."""
    mcs = _MCS.search(line)
    rate = _RATE.search(line)
    signal = _SIGNAL.search(line)
    addrs: dict[str, str] = {}
    order: list[str] = []
    for label, mac in _ADDR.findall(line):
        if label not in addrs:
            addrs[label] = mac.lower()
            order.append(label)
    if mcs is None and rate is None and signal is None and not addrs:
        return None
    return Frame(
        rate=f"MCS {mcs.group(1)}" if mcs else rate.group(1) if rate else None,
        signal_dbm=int(signal.group(1)) if signal else None,
        bad_fcs="bad-fcs" in line,
        retry=re.search(r"\bRetry\b", line) is not None,
        src=_transmitter(addrs, order),
        bssid=addrs.get("BSSID"),
        dst=addrs.get("RA") or addrs.get("DA"),
    )


def _transmitter(addrs: Mapping[str, str], order: list[str]) -> str | None:
    """Address 2, by the order tcpdump prints the labels in: FromDS data is `DA BSSID SA` (the AP sent it, SA
    is where it came from on the LAN), 4-address data `RA TA DA SA` and control frames carry TA; every other
    frame's SA is its sender."""
    if order[:3] == ["DA", "BSSID", "SA"]:
        return addrs["BSSID"]
    return addrs.get("TA") or addrs.get("SA")


def _signal_bin(dbm: int) -> int:
    return math.floor(dbm / SIGNAL_BIN_DB) * SIGNAL_BIN_DB


class _Tally:
    def __init__(self) -> None:
        self.frames = 0
        self.retries = 0
        self.rates: Counter[str] = Counter()
        self.signals: Counter[int] = Counter()

    def add(self, f: Frame) -> None:
        self.frames += 1
        self.retries += f.retry
        if f.rate is not None:
            self.rates[f.rate] += 1
        if f.signal_dbm is not None:
            self.signals[_signal_bin(f.signal_dbm)] += 1

    def done(self) -> Direction:
        return Direction(self.frames, self.retries, dict(self.rates), dict(self.signals))


def summarize(stdout: str, stderr: str, own: Collection[str], seconds: float) -> FrameWindow:
    mine = {m.lower() for m in own}
    rx, tx = _Tally(), _Tally()
    frames = bad = 0
    for line in stdout.splitlines():
        f = parse_frame(line)
        if f is None:
            continue
        frames += 1
        if f.bad_fcs:
            bad += 1
            continue
        if f.src in mine:
            tx.add(f)
        elif f.src is not None and (f.bssid in mine or f.dst in mine):
            rx.add(f)
    dropped = _DROPPED.search(stderr)
    return FrameWindow(
        seconds=seconds,
        frames=frames,
        bad_fcs=bad,
        rx=rx.done(),
        tx=tx.done(),
        dropped=int(dropped.group(1)) if dropped else None,
    )


def _merge[K: (str, int)](a: Mapping[K, int], b: Mapping[K, int]) -> dict[K, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def _join(a: Direction, b: Direction) -> Direction:
    rates = _merge(a.rates, b.rates)
    return Direction(a.frames + b.frames, a.retries + b.retries, rates, _merge(a.signal_hist, b.signal_hist))


def combine(a: FrameWindow, b: FrameWindow) -> FrameWindow:
    """The totals since Start."""
    dropped = None if a.dropped is None and b.dropped is None else (a.dropped or 0) + (b.dropped or 0)
    return FrameWindow(
        seconds=a.seconds + b.seconds,
        frames=a.frames + b.frames,
        bad_fcs=a.bad_fcs + b.bad_fcs,
        rx=_join(a.rx, b.rx),
        tx=_join(a.tx, b.tx),
        dropped=dropped,
    )
