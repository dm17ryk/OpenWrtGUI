"""RF samples to CSV: one row per station per second (one row with empty station columns when none)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from openwrtgui.rf.sample import RfSample, StationSample

COLUMNS = (
    "time",
    "router",
    "radio",
    "channel",
    "width_mhz",
    "txpower_dbm",
    "busy_pct",
    "ack_fail_per_s",
    "station",
    "name",
    "signal_dbm",
    "signal_avg_dbm",
    "rx_mbps",
    "rx_mode",
    "tx_mbps",
    "tx_mcs",
    "tx_mode",
    "retry_pct",
    "failed_per_s",
    "rx_pps",
    "tx_pps",
    "expected_mbps",
)


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _station_cells(s: StationSample | None) -> list[Any]:
    if s is None:
        return [None] * 14
    return [
        s.mac,
        s.name,
        s.signal_dbm,
        s.signal_avg_dbm,
        s.rx.mbps if s.rx else None,
        s.rx.mode if s.rx else None,
        s.tx.mbps if s.tx else None,
        s.tx.mcs if s.tx else None,
        s.tx.mode if s.tx else None,
        s.retry_pct,
        s.failed_per_s,
        s.rx_pps,
        s.tx_pps,
        s.expected_mbps,
    ]


class CsvRecorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w", encoding="utf-8", newline="")
        self._csv = csv.writer(self._file)
        self._csv.writerow(COLUMNS)

    def write(self, sample: RfSample) -> None:
        r = sample.radio_sample
        head = [
            sample.at.isoformat(timespec="seconds"),
            sample.router_id,
            sample.radio,
            r.channel,
            r.width_mhz,
            r.txpower_dbm,
            r.busy_pct,
            r.ack_fail_per_s,
        ]
        for station in sample.stations or (None,):
            self._csv.writerow([_cell(v) for v in head + _station_cells(station)])
        self._file.flush()

    def close(self) -> None:
        self._file.close()
