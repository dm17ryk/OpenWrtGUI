"""The step-through's record (v0.7 plan D10): one CSV row per step, written as each step ends."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openwrtgui.wifi.step_service import StepResult

HEADER = (
    "step",
    "mode",
    "channel",
    "txpower_dbm",
    "proven",
    "failed_checks",
    "beacon",
    "rejoin_s",
    "started",
    "ended",
)


class StepCsv:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("x", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(HEADER)
        self._file.flush()

    def write(self, r: StepResult) -> None:
        failed = "; ".join(f"{c.name}: {c.detail}" for c in r.checks if c.ok is False)
        rejoin = "" if r.rejoined is None else f"{r.rejoin_s:.1f}" if r.rejoined else "not re-joined"
        self._writer.writerow(
            (
                r.index,
                r.mode,
                r.channel,
                "" if r.txpower_dbm is None else r.txpower_dbm,
                "yes" if r.proven else "no",
                failed,
                r.beacon or "",
                rejoin,
                r.started_at.isoformat(timespec="seconds"),
                r.ended_at.isoformat(timespec="seconds") if r.ended_at else "",
            )
        )
        self._file.flush()  # a crash keeps the steps already done

    def close(self) -> None:
        self._file.close()
