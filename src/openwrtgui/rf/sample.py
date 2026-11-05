"""One RF read (a single exec on the router) and the per-second rates derived from two reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from openwrtgui.rf.parse import Bitrate, StationRaw, SurveyEntry
from openwrtgui.wifi.parse import IwDevInfo


def rf_command(ifname: str, phy: str) -> str:
    """Everything one sample needs in one exec, sectioned with ===NAME lines."""
    return (
        f"echo ===STA; iw dev {ifname} station dump; echo ===SURVEY; iw dev {ifname} survey dump; "
        f"echo ===ACK; cat /sys/kernel/debug/ieee80211/{phy}/statistics/dot11ACKFailureCount 2>/dev/null; "
        f"echo ===INFO; iw dev {ifname} info"
    )


@dataclass(frozen=True)
class RawTick:
    at: datetime
    stations: tuple[StationRaw, ...]
    survey: SurveyEntry | None
    ack_failures: int | None
    info: IwDevInfo


@dataclass(frozen=True)
class RadioSample:
    channel: int | None
    freq_mhz: int | None
    width_mhz: int | None
    txpower_dbm: float | None
    busy_pct: float | None
    noise_dbm: int | None
    ack_fail_per_s: float | None


@dataclass(frozen=True)
class StationSample:
    mac: str
    name: str | None
    signal_dbm: int | None
    signal_avg_dbm: int | None
    chains: tuple[int, ...]
    rx: Bitrate | None
    tx: Bitrate | None
    rx_pps: float | None
    rx_kbps: float | None
    tx_pps: float | None
    tx_kbps: float | None
    retry_pct: float | None
    failed_per_s: float | None
    rx_drops: int | None
    inactive_ms: int | None
    expected_mbps: float | None
    ack_signal_dbm: int | None


@dataclass(frozen=True)
class RfSample:
    at: datetime
    router_id: str
    radio: str
    ifname: str
    radio_sample: RadioSample
    stations: tuple[StationSample, ...]
    left: tuple[str, ...]


def _delta(new: int | None, old: int | None) -> int | None:
    """A counter's increase; None when unknown or when it went backwards (a reset or a new station)."""
    if new is None or old is None or new < old:
        return None
    return new - old


def _per_s(delta: int | None, dt: float | None, scale: float = 1.0) -> float | None:
    return round(delta * scale / dt, 3) if delta is not None and dt else None


def _station(cur: StationRaw, prev: StationRaw | None, dt: float | None, name: str | None) -> StationSample:
    p = prev if dt else None
    d_tx = _delta(cur.tx_packets, p.tx_packets) if p else None
    d_retries = _delta(cur.tx_retries, p.tx_retries) if p else None
    return StationSample(
        mac=cur.mac,
        name=name,
        signal_dbm=cur.signal_dbm,
        signal_avg_dbm=cur.signal_avg_dbm,
        chains=cur.chains,
        rx=cur.rx,
        tx=cur.tx,
        rx_pps=_per_s(_delta(cur.rx_packets, p.rx_packets) if p else None, dt),
        rx_kbps=_per_s(_delta(cur.rx_bytes, p.rx_bytes) if p else None, dt, 8 / 1000),
        tx_pps=_per_s(d_tx, dt),
        tx_kbps=_per_s(_delta(cur.tx_bytes, p.tx_bytes) if p else None, dt, 8 / 1000),
        retry_pct=round(100 * d_retries / d_tx, 2) if d_retries is not None and d_tx else None,
        failed_per_s=_per_s(_delta(cur.tx_failed, p.tx_failed) if p else None, dt),
        rx_drops=cur.rx_drop_misc,
        inactive_ms=cur.inactive_ms,
        expected_mbps=cur.expected_mbps,
        ack_signal_dbm=cur.ack_signal_dbm,
    )


def derive(
    prev: RawTick | None, cur: RawTick, router_id: str, radio: str, names: Mapping[str, str]
) -> RfSample:
    dt = (cur.at - prev.at).total_seconds() if prev else None
    busy = None
    # Survey counters are per channel: a delta across a channel change means nothing.
    if prev and prev.survey and cur.survey and prev.survey.freq_mhz == cur.survey.freq_mhz:
        d_active = _delta(cur.survey.active_ms, prev.survey.active_ms)
        d_busy = _delta(cur.survey.busy_ms, prev.survey.busy_ms)
        if d_active and d_busy is not None and d_busy <= d_active:
            busy = round(100 * d_busy / d_active, 1)
    before = {s.mac: s for s in prev.stations} if prev else {}
    return RfSample(
        at=cur.at,
        router_id=router_id,
        radio=radio,
        ifname=cur.info.ifname,
        radio_sample=RadioSample(
            channel=cur.info.channel,
            freq_mhz=cur.info.freq_mhz,
            width_mhz=cur.info.width_mhz,
            txpower_dbm=cur.info.txpower_dbm,
            busy_pct=busy,
            noise_dbm=cur.survey.noise_dbm if cur.survey else None,
            ack_fail_per_s=_per_s(_delta(cur.ack_failures, prev.ack_failures) if prev else None, dt),
        ),
        stations=tuple(_station(s, before.get(s.mac), dt, names.get(s.mac)) for s in cur.stations),
        left=tuple(mac for mac in before if mac not in {s.mac for s in cur.stations}),
    )
