"""AP2's recorded minstrel rates (tests/fixtures/ap2/rates.json, 2026-11-19 v1.1b window, the bench phone
on OwgTest, channel 11, pinging AP2) against the v1.1b parser, which was written from the kernel source
before any real `rc_stats_csv` was seen (plan ruling R3). The recording keeps the kernel's format: 18
fields a line, no header, and minstrel's first-choice rate flagged `A` is the rate `iw station dump`
reports as the tx bitrate."""

from __future__ import annotations

import json
import re
from pathlib import Path

from openwrtgui.rf.rates import FIELDS, parse_rc_stats_csv

RECORDING: dict[str, dict[str, object]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "rates.json").read_text(encoding="utf-8")
)


def _out(command: str) -> str:
    entry = RECORDING[command]
    assert entry["exit"] == 0, entry
    return str(entry["stdout"])


def _rc_stats() -> str:
    (command,) = [c for c in RECORDING if c.endswith("/rc_stats_csv")]
    return _out(command)


def test_every_line_is_the_kernels_csv() -> None:
    """No line is skipped as unreadable: each has the 18 fields the parser expects, and no header."""
    lines = [line for line in _rc_stats().splitlines() if line.strip()]
    assert len(lines) == 32  # HT20, long and short GI, MCS0-15
    assert all(len(line.split(",")) == FIELDS for line in lines)
    assert all(line.startswith("HT20,") for line in lines)


def test_one_rate_in_use_and_every_success_rate_sane() -> None:
    rows = parse_rc_stats_csv(_rc_stats())
    assert len(rows) == 30  # 2 short-GI rates were never tried
    in_use = [r for r in rows if r.in_use]
    assert [(r.mode, r.rate) for r in in_use] == [("HT20 LGI", "MCS13")]
    assert all(0.0 <= r.success_pct <= 100.0 for r in rows)
    assert all(r.attempts > 0 for r in rows)


def test_the_rate_in_use_is_the_stations_tx_bitrate() -> None:
    """Minstrel's `A` flag is the rate the radio sends with: `iw` reports it as the station's tx bitrate."""
    dump = _out("iw dev phy0-ap0 station dump")
    assert re.search(r"tx bitrate:\s+104\.0 MBit/s MCS 13\n", dump)  # HT20, long GI, MCS13


def test_the_recording_keeps_no_real_station_address() -> None:
    macs = set(re.findall(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", json.dumps(RECORDING), flags=re.IGNORECASE))
    assert macs == {"02:00:00:00:00:01"}
