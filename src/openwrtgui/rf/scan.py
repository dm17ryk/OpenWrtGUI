"""Channel analysis (v0.7 plan D13): the networks an `iw dev X scan` heard and each channel's load.

iw prints an SSID with every byte that is not printable (and a backslash, or a space at either end) as
`\\xNN`; a hidden SSID is empty or only NULs. A channel's busy share comes from two survey dumps around the
scan: the radio visits each channel while it scans, and the driver counts its active and busy time there.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from openwrtgui.rf.parse import SurveyEntry

Security = Literal["open", "WEP", "WPA", "WPA2", "WPA3", "WPA2/WPA3"]
Secondary = Literal["above", "below"]

_BSS = re.compile(r"BSS ([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\(on [^)]*\)")
_FREQ = re.compile(r"freq:\s*(\d+)(?:\.\d+)?")
_SIGNAL = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?) dBm")
_LAST_SEEN = re.compile(r"last seen:\s*(\d+) ms ago")
_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")


@dataclass(frozen=True)
class Bss:
    bssid: str
    ssid: str | None  # None: hidden (empty, or only \x00)
    freq_mhz: int
    channel: int | None
    signal_dbm: float | None
    width_mhz: int  # 20, or 40 with a secondary channel
    secondary: Secondary | None
    security: Security
    last_seen_ms: int | None
    own: bool


@dataclass(frozen=True)
class ChannelLoad:
    channel: int
    freq_mhz: int
    busy_pct: float | None  # None: the scan did not visit it (no active-time increase)
    networks: int  # BSSs whose occupied band overlaps it
    strongest_dbm: float | None


def channel_of(freq_mhz: int) -> int | None:
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5150 <= freq_mhz <= 5895:
        return (freq_mhz - 5000) // 5
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5
    return None


def freq_of(channel: int, band: str = "2g") -> int:
    if band == "2g":
        return 2484 if channel == 14 else 2407 + 5 * channel
    return (5950 if band == "6g" else 5000) + 5 * channel


def _ssid(raw: str) -> str | None:
    data = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), raw).encode("latin-1", "replace")
    if not data.strip(b"\x00 "):
        return None
    return data.decode("utf-8", "replace")


def _security(suites: dict[str, str], privacy: bool) -> Security:
    rsn = suites.get("RSN")
    if rsn is not None:
        psk, sae = "PSK" in rsn.split() or "802.1X" in rsn, "SAE" in rsn.split()
        if psk and sae:
            return "WPA2/WPA3"
        return "WPA3" if sae else "WPA2"
    if "WPA" in suites:
        return "WPA"
    return "WEP" if privacy else "open"


def _block(bssid: str, lines: Sequence[str], own: Collection[str]) -> Bss | None:
    freq = signal = last_seen = None
    raw_ssid = ""
    secondary: Secondary | None = None
    privacy = False
    section = ""
    suites: dict[str, str] = {}
    for line in lines:
        if line.startswith("\t") and not line.startswith("\t\t"):
            section = line.strip().split(":", 1)[0]
        text = line.strip()
        if section in ("RSN", "WPA"):
            suites.setdefault(section, "")
        if m := _FREQ.match(text):
            freq = int(m.group(1))
        elif m := _SIGNAL.match(text):
            signal = float(m.group(1))
        elif m := _LAST_SEEN.match(text):
            last_seen = int(m.group(1))
        elif text.startswith("SSID:"):
            raw_ssid = text[len("SSID:") :].strip()
        elif text.startswith("capability:"):
            privacy = "Privacy" in text.split()
        elif "Authentication suites:" in text and section in ("RSN", "WPA"):
            suites[section] = text.split("Authentication suites:", 1)[1]
        elif "secondary channel offset:" in text:
            offset = text.split("secondary channel offset:", 1)[1].strip()
            secondary = "above" if offset == "above" else "below" if offset == "below" else None
    if freq is None:
        return None
    return Bss(
        bssid=bssid,
        ssid=_ssid(raw_ssid),
        freq_mhz=freq,
        channel=channel_of(freq),
        signal_dbm=signal,
        width_mhz=40 if secondary else 20,
        secondary=secondary,
        security=_security(suites, privacy),
        last_seen_ms=last_seen,
        own=bssid in own,
    )


def parse_scan(text: str, own: Collection[str] = ()) -> list[Bss]:
    mine = {m.lower() for m in own}
    out: list[Bss] = []
    bssid: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if bssid is not None and (b := _block(bssid, lines, mine)) is not None:
            out.append(b)

    for line in text.splitlines():
        if m := _BSS.match(line):
            flush()
            bssid, lines = m.group(1).lower(), []
        elif bssid is not None:
            lines.append(line)
    flush()
    return out


def _band(b: Bss) -> tuple[float, float]:
    centre = b.freq_mhz + (10 if b.secondary == "above" else -10 if b.secondary == "below" else 0)
    return centre - b.width_mhz / 2, centre + b.width_mhz / 2


def _busy(before: SurveyEntry | None, after: SurveyEntry | None) -> float | None:
    if before is None or after is None:
        return None
    values = (before.active_ms, before.busy_ms, after.active_ms, after.busy_ms)
    if any(v is None for v in values):
        return None
    d_active = (after.active_ms or 0) - (before.active_ms or 0)
    d_busy = (after.busy_ms or 0) - (before.busy_ms or 0)
    if d_active <= 0 or d_busy < 0 or d_busy > d_active:
        return None
    return round(100 * d_busy / d_active, 1)


def channel_loads(
    before: Sequence[SurveyEntry],
    after: Sequence[SurveyEntry],
    bss: Sequence[Bss],
    channels: Iterable[int],
    band: str = "2g",
) -> list[ChannelLoad]:
    was = {s.freq_mhz: s for s in before}
    now = {s.freq_mhz: s for s in after}
    out = []
    for channel in sorted(channels):
        freq = freq_of(channel, band)
        heard = [b for b in bss if _band(b)[0] < freq < _band(b)[1]]
        signals = [b.signal_dbm for b in heard if b.signal_dbm is not None]
        out.append(
            ChannelLoad(
                channel=channel,
                freq_mhz=freq,
                busy_pct=_busy(was.get(freq), now.get(freq)),
                networks=len(heard),
                strongest_dbm=max(signals) if signals else None,
            )
        )
    return out
