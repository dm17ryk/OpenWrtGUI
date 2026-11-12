"""tools/record_fixtures.py: neighbour networks are replaced in air recordings (v0.7 plan D14)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "record_fixtures.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


rf = _load()

OWN = "00:0c:43:76:20:18"
SCAN = (
    "BSS 3c:84:6a:11:22:33(on owgscan0)\n"
    "\tSSID: Office-5\n"
    "BSS a4:91:b1:44:55:66(on owgscan0)\n"
    "\tSSID: Caf\\xc3\\xa9\n"
    f"BSS {OWN}(on owgscan0)\n"
    "\tSSID: OwgTest\n"
)
FRAME = (
    "23:54:52.943020 6.0 Mb/s 2437 MHz 11g -61dBm signal BSSID:3c:84:6a:11:22:33 "
    "DA:ff:ff:ff:ff:ff:ff SA:3c:84:6a:11:22:33 Beacon (Office-5) [6.0* Mbit] ESS CH: 6\n"
    "23:54:52.950000 1.0 Mb/s 2437 MHz 11b -70dBm signal DA:01:00:5e:00:00:fb BSSID:a4:91:b1:44:55:66 "
    "SA:a4:91:b1:44:55:66 Data IV\n"
)


def test_air_sanitizer_replaces_neighbours() -> None:
    names: dict[str, str] = {}
    scan = rf.sanitize_air(SCAN, {OWN}, {"OwgTest"}, names)
    assert "3c:84:6a:11:22:33" not in scan and "a4:91:b1:44:55:66" not in scan
    assert "BSS 02:00:00:00:00:01(on owgscan0)" in scan
    assert "BSS 02:00:00:00:00:02(on owgscan0)" in scan
    assert "\tSSID: net-01\n" in scan and "\tSSID: net-02\n" in scan
    assert "Office-5" not in scan and "Caf" not in scan
    assert f"BSS {OWN}(on owgscan0)" in scan and "\tSSID: OwgTest\n" in scan

    frame = rf.sanitize_air(FRAME, {OWN}, {"OwgTest"}, names)
    assert "BSSID:02:00:00:00:00:01" in frame and "SA:02:00:00:00:00:02" in frame
    assert "Beacon (net-01)" in frame
    assert "DA:ff:ff:ff:ff:ff:ff" in frame and "DA:01:00:5e:00:00:fb" in frame


def test_air_sanitizer_is_stable_within_a_file() -> None:
    names: dict[str, str] = {}
    first = rf.sanitize_air(SCAN, {OWN}, {"OwgTest"}, names)
    again = rf.sanitize_air(SCAN, {OWN}, {"OwgTest"}, names)
    assert first == again


def test_air_sanitizer_keeps_placeholders() -> None:
    text = "BSS 02:00:00:00:00:07(on owgscan0)\n\tSSID: net-07\n"
    assert rf.sanitize_air(text, set(), set(), {}) == text
