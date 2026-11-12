"""AP2's air recording (v0.7 plan Task 3, HW-1) through the scan and frame parsers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openwrtgui.rf.air import SCAN_IF, scan_command, survey_command
from openwrtgui.rf.parse import parse_survey
from openwrtgui.rf.scan import channel_loads, parse_scan

AIR = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "air.json"
AFTER = " #after-scan"


def _air() -> dict[str, str]:
    if not AIR.exists():
        pytest.skip("tests/fixtures/ap2/air.json is recorded in the AP2 window HW-1 (plan Task 3)")
    recorded = json.loads(AIR.read_text(encoding="utf-8"))
    return {cmd: str(entry.get("stdout", "")) for cmd, entry in recorded.items()}


def test_parse_ap2_scan() -> None:
    air = _air()
    text = air[scan_command(SCAN_IF, on_ap=False)]
    networks = parse_scan(text)
    assert len(networks) == sum(1 for line in text.splitlines() if line.startswith("BSS "))
    assert all(b.channel is not None for b in networks)
    before = parse_survey(air[survey_command(SCAN_IF)])
    after = parse_survey(air[survey_command(SCAN_IF) + AFTER])
    loads = channel_loads(before, after, networks, range(1, 14))
    assert any(c.busy_pct is not None for c in loads)
