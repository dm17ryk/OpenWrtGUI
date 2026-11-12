"""tools/record_fixtures.py: neighbour networks are replaced in air recordings (v0.7 plan D14)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from openwrtgui.rf.air import FRAME_WINDOW

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


SCAN_FULL = (
    "BSS 3c:84:6a:11:22:33(on owgscan0)\n"
    "\tlast seen: 1234.567s [boottime]\n"
    "\tTSF: 123456789 usec (0d, 00:02:03)\n"
    "\tfreq: 2437.0\n"
    "\tbeacon interval: 100 TUs\n"
    "\tcapability: ESS Privacy ShortSlotTime (0x0411)\n"
    "\tsignal: -61.00 dBm\n"
    "\tlast seen: 160 ms ago\n"
    "\tSSID: Office-5\n"
    "\tDS Parameter set: channel 6\n"
    "\tRSN:\t * Version: 1\n"
    "\t\t * Group cipher: CCMP\n"
    "\t\t * Authentication suites: PSK\n"
    "\tHT operation:\n"
    "\t\t * primary channel: 6\n"
    "\t\t * secondary channel offset: no secondary\n"
    "\tWPS:\t * Version: 1.0\n"
    "\t\t * Manufacturer: Acme Printers\n"
    "\t\t * Model: Laser 2000\n"
    "\t\t * Device name: Johns-Printer\n"
    "\t\t * Serial Number: 3C846A112233\n"
    "\t\t * UUID: 1234abcd-0000-1000-8000-3c846a112233\n"
    "\tMESH ID: home-mesh\n"
)


def test_trim_scan_keeps_only_what_the_parser_reads() -> None:
    from openwrtgui.rf.scan import parse_scan

    trimmed = rf.trim_air("iw dev owgscan0 scan passive", SCAN_FULL)
    for leak in ("Acme", "Laser", "Johns-Printer", "3C846A112233", "1234abcd", "home-mesh", "TSF"):
        assert leak not in trimmed, leak
    assert parse_scan(trimmed) == parse_scan(SCAN_FULL)


def test_trim_frames_cuts_after_the_type() -> None:
    from openwrtgui.rf.frames import parse_frame

    data = (
        "10:00:01.000100 1234567us tsft 54.0 Mb/s 2437 MHz 11g -52dBm signal antenna 0 Retry 44us "
        "BSSID:3c:84:6a:11:22:33 SA:a4:91:b1:44:55:66 DA:3c:84:6a:11:22:33 Data IV:1 Pad 20 KeyID 0 "
        "IP 192.168.7.50.5353 > 224.0.0.251.5353: 0 PTR (QM)? johns-laptop.local."
    )
    beacon = (
        "10:00:01.000200 1.0 Mb/s 2437 MHz 11b -70dBm signal antenna 0 BSSID:3c:84:6a:11:22:33 "
        "DA:ff:ff:ff:ff:ff:ff SA:3c:84:6a:11:22:33 Beacon (Bob's (home)) [1.0* 2.0* Mbit] ESS CH: 6, PRIVACY"
    )
    trimmed = rf.trim_air(FRAME_WINDOW, data + "\n" + beacon + "\n")
    assert "johns-laptop" not in trimmed and "192.168.7.50" not in trimmed and "IV:1" not in trimmed
    assert trimmed.splitlines()[0].endswith("DA:3c:84:6a:11:22:33 Data")
    assert parse_frame(trimmed.splitlines()[0]) == parse_frame(data)
    names: dict[str, str] = {}
    clean = rf.sanitize_air(trimmed, set(), set(), names)
    assert "Bob" not in clean and "home" not in clean
    assert clean.splitlines()[1].endswith("Beacon (net-01)")


def test_trim_frames_drops_payload_lines_and_keeps_tcpdump_status() -> None:
    from openwrtgui.rf.frames import summarize

    stdout = (
        "10:00:01.000100 1.0 Mb/s 2437 MHz 11b -70dBm signal BSSID:3c:84:6a:11:22:33 "
        "SA:a4:91:b1:44:55:66 DA:ff:ff:ff:ff:ff:ff Data IV:1 BOOTP/DHCP, Request\n"
        "\t  Client-Ethernet-Address a4:91:b1:44:55:66\n"
        '\t    Hostname Option 12, length 12: "johns-laptop"\n'
    )
    stderr = (
        "tcpdump: listening on owgmon0, link-type IEEE802_11_RADIO, snapshot length 128 bytes\n"
        "1 packet captured\n3 packets received by filter\n0 packets dropped by kernel\n"
    )
    out = rf.trim_air(FRAME_WINDOW, stdout)
    assert "johns-laptop" not in out and "Client-Ethernet" not in out
    assert out.count("\n") == 1
    assert rf.trim_air(FRAME_WINDOW, stderr) == stderr
    assert summarize(out, stderr, set(), 3.0) == summarize(stdout, stderr, set(), 3.0)


def test_bad_fcs_addresses_are_replaced_even_with_the_group_bit() -> None:
    """HW-1 by eye: a corrupted frame's addresses can carry the group bit and still be a bit away from a real
    station's MAC. In a bad-FCS line only broadcast, the router's own and placeholders stay."""
    bad = (
        "07:24:36.264260 bad-fcs 1.0 Mb/s 2437 MHz 11b -58dBm signal antenna 1 0us BSSID:0b:ad:fc:5c:00:01 "
        "DA:ff:ff:0b:ad:fc:02 SA:0b:ad:fc:5c:00:01 Beacon ()\n"
    )
    good = (
        "07:24:36.300000 1.0 Mb/s 2437 MHz 11b -60dBm signal antenna 1 0us BSSID:3c:84:6a:11:22:33 "
        "DA:01:00:5e:00:00:fb SA:3c:84:6a:11:22:33 Data\n"
    )
    names: dict[str, str] = {}
    clean = rf.sanitize_air(bad + good, {OWN}, set(), names)
    assert "0b:ad:fc:5c:00:01" not in clean and "ff:ff:0b:ad:fc:02" not in clean
    assert "SA:02:00:00:00:00:01 Beacon" in clean
    assert "DA:01:00:5e:00:00:fb" in clean  # a real multicast group in a good frame stays
    assert rf.sanitize_air(f"x bad-fcs DA:ff:ff:ff:ff:ff:ff SA:{OWN} Beacon ()\n", {OWN}, set(), {}).endswith(
        f"DA:ff:ff:ff:ff:ff:ff SA:{OWN} Beacon ()\n"
    )


def test_trim_air_is_idempotent() -> None:
    """The contract test checks a recording by trimming it again: a trimmed text must not change."""
    once = rf.trim_air("iw dev owgscan0 scan passive", SCAN_FULL)
    assert rf.trim_air("iw dev owgscan0 scan passive", once) == once
    frames = rf.trim_air(FRAME_WINDOW, FRAME)
    assert rf.trim_air(FRAME_WINDOW, frames) == frames
