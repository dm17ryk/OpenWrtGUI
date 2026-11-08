"""Signal quality labels (v0.6a plan D11, common LTE field thresholds): a boundary is the better label."""

from __future__ import annotations

from typing import Literal

Quality = Literal["excellent", "good", "fair", "poor"]
Metric = Literal["rssi", "rsrp", "rsrq", "snr"]

# excellent, good, fair: the lowest value of each band
THRESHOLDS: dict[Metric, tuple[float, float, float]] = {
    "rsrp": (-80, -90, -100),
    "rsrq": (-10, -15, -20),
    "snr": (20, 13, 0),
    "rssi": (-65, -75, -85),
}


def label(metric: Metric, value: float) -> Quality:
    excellent, good, fair = THRESHOLDS[metric]
    if value >= excellent:
        return "excellent"
    if value >= good:
        return "good"
    if value >= fair:
        return "fair"
    return "poor"
