"""Parsers for `iw dev <if> station dump` and `survey dump`, and the sectioned output of one RF read."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CCK_MBPS = (1.0, 2.0, 5.5, 11.0)
RateMode = Literal["b", "g", "n20", "n40"]
_BITRATE = re.compile(r"([\d.]+) MBit/s(?: MCS (\d+))?")
_DBM_CHAINS = re.compile(r"(-?\d+)(?: \[([-\d, ]+)\])? dBm")


@dataclass(frozen=True)
class Bitrate:
    mbps: float
    mcs: int | None
    width_mhz: int
    short_gi: bool
    mode: RateMode


@dataclass(frozen=True)
class StationRaw:
    mac: str
    inactive_ms: int | None
    rx_bytes: int | None
    rx_packets: int | None
    tx_bytes: int | None
    tx_packets: int | None
    tx_retries: int | None
    tx_failed: int | None
    rx_drop_misc: int | None
    signal_dbm: int | None
    chains: tuple[int, ...]
    signal_avg_dbm: int | None
    avg_chains: tuple[int, ...]
    tx: Bitrate | None
    rx: Bitrate | None
    expected_mbps: float | None
    ack_signal_dbm: int | None
    connected_s: int | None


@dataclass(frozen=True)
class SurveyEntry:
    freq_mhz: int
    in_use: bool
    noise_dbm: int | None
    active_ms: int | None
    busy_ms: int | None


def parse_bitrate(text: str) -> Bitrate | None:
    m = _BITRATE.search(text)
    if m is None:
        return None
    mbps = float(m.group(1))
    if m.group(2) is not None:
        wide = "40MHz" in text
        return Bitrate(
            mbps, int(m.group(2)), 40 if wide else 20, "short GI" in text, "n40" if wide else "n20"
        )
    return Bitrate(mbps, None, 20, False, "b" if mbps in CCK_MBPS else "g")


def _int(text: str) -> int | None:
    m = re.match(r"-?\d+", text.strip())
    return int(m.group(0)) if m else None


def _dbm(text: str) -> tuple[int | None, tuple[int, ...]]:
    m = _DBM_CHAINS.search(text)
    if m is None:
        return None, ()
    chains = tuple(int(c) for c in m.group(2).split(",")) if m.group(2) else ()
    return int(m.group(1)), chains


_INT_FIELDS = {
    "inactive time": "inactive_ms",
    "rx bytes": "rx_bytes",
    "rx packets": "rx_packets",
    "tx bytes": "tx_bytes",
    "tx packets": "tx_packets",
    "tx retries": "tx_retries",
    "tx failed": "tx_failed",
    "rx drop misc": "rx_drop_misc",
    "connected time": "connected_s",
}


def _station(mac: str, fields: dict[str, str]) -> StationRaw:
    values: dict[str, object] = {
        attr: _int(fields[key]) if key in fields else None for key, attr in _INT_FIELDS.items()
    }
    signal, chains = _dbm(fields.get("signal", ""))
    avg, avg_chains = _dbm(fields.get("signal avg", ""))
    ack, _ = _dbm(fields.get("ack signal", ""))
    expected = re.match(r"([\d.]+)", fields.get("expected throughput", "").strip())
    return StationRaw(
        mac=mac,
        signal_dbm=signal,
        chains=chains,
        signal_avg_dbm=avg,
        avg_chains=avg_chains,
        tx=parse_bitrate(fields.get("tx bitrate", "")),
        rx=parse_bitrate(fields.get("rx bitrate", "")),
        expected_mbps=float(expected.group(1)) if expected else None,
        ack_signal_dbm=ack,
        **values,  # type: ignore[arg-type]
    )


def parse_station_dump(text: str) -> list[StationRaw]:
    out: list[StationRaw] = []
    mac: str | None = None
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        if m := re.match(r"Station ([0-9a-f:]{17}) ", raw):
            if mac:
                out.append(_station(mac, fields))
            mac, fields = m.group(1), {}
        elif mac and ":" in raw:
            key, _, value = raw.strip().partition(":")
            fields[key.strip()] = value.strip()
    if mac:
        out.append(_station(mac, fields))
    return out


def current_survey(entries: list[SurveyEntry], freq_mhz: int | None) -> SurveyEntry | None:
    """The entry of the radio's own frequency: rt2800 (AP2) marks every channel "[in use]"."""
    if freq_mhz is None:
        return next((s for s in entries if s.in_use), None)
    return next((s for s in entries if s.freq_mhz == freq_mhz), None)


def parse_survey(text: str) -> list[SurveyEntry]:
    out: list[SurveyEntry] = []
    block: dict[str, str] | None = None

    def flush() -> None:
        if block and (m := re.match(r"(\d+) MHz", block.get("frequency", ""))):
            out.append(
                SurveyEntry(
                    freq_mhz=int(m.group(1)),
                    in_use="[in use]" in block["frequency"],
                    noise_dbm=_int(block["noise"]) if "noise" in block else None,
                    active_ms=_int(block["channel active time"]) if "channel active time" in block else None,
                    busy_ms=_int(block["channel busy time"]) if "channel busy time" in block else None,
                )
            )

    for raw in text.splitlines():
        if raw.startswith("Survey data from"):
            flush()
            block = {}
        elif block is not None and ":" in raw:
            key, _, value = raw.strip().partition(":")
            block[key.strip()] = value.strip()
    flush()
    return out


def split_sections(text: str) -> dict[str, str]:
    """`===NAME` lines start a section; returns {NAME: its text without the trailing newline}."""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if m := re.fullmatch(r"===(\w+)", line.strip()):
            current = sections.setdefault(m.group(1), [])
        elif current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}
