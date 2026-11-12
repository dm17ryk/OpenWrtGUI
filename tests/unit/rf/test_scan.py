"""Channel analysis: `iw dev X scan` results and each channel's load (v0.7 plan Task 4)."""

from __future__ import annotations

from openwrtgui.rf.parse import SurveyEntry
from openwrtgui.rf.scan import Bss, channel_loads, channel_of, freq_of, parse_scan


def _bss(
    mac: str,
    ssid: str,
    freq: float,
    signal: float,
    *,
    secondary: str | None = None,
    security: str = "",
    capability: str = "ESS ShortSlotTime (0x0401)",
    head: str = "",
) -> str:
    lines = [
        f"BSS {mac}(on owgscan0){head}",
        "\tlast seen: 1234.567s [boottime]",
        "\tTSF: 123456789 usec (0d, 00:02:03)",
        f"\tfreq: {freq}",
        "\tbeacon interval: 100 TUs",
        f"\tcapability: {capability}",
        f"\tsignal: {signal:.2f} dBm",
        "\tlast seen: 120 ms ago",
        "\tInformation elements from Probe Response frame:",
        f"\tSSID: {ssid}",
        "\tSupported rates: 1.0* 2.0* 5.5* 11.0* 6.0 9.0 12.0 18.0 ",
        "\tDS Parameter set: channel 6",
    ]
    lines += security.splitlines()
    if secondary is not None:
        lines += [
            "\tHT operation:",
            "\t\t * primary channel: 6",
            f"\t\t * secondary channel offset: {secondary}",
            "\t\t * STA channel width: any",
        ]
    return "\n".join(lines) + "\n"


RSN_PSK = (
    "\tRSN:\t * Version: 1\n\t\t * Group cipher: CCMP\n"
    "\t\t * Pairwise ciphers: CCMP\n\t\t * Authentication suites: PSK\n"
)
RSN_MIXED = RSN_PSK.replace("suites: PSK", "suites: PSK SAE")
RSN_SAE = RSN_PSK.replace("suites: PSK", "suites: SAE")
WPA1 = "\tWPA:\t * Version: 1\n\t\t * Group cipher: TKIP\n\t\t * Authentication suites: PSK\n"


def test_parse_one_bss() -> None:
    text = _bss("3c:84:6a:11:22:33", "Office-5", 2437.0, -56, secondary="no secondary", security=RSN_PSK)
    [b] = parse_scan(text)
    assert b == Bss(
        bssid="3c:84:6a:11:22:33",
        ssid="Office-5",
        freq_mhz=2437,
        channel=6,
        signal_dbm=-56.0,
        width_mhz=20,
        secondary=None,
        security="WPA2",
        last_seen_ms=120,
        own=False,
    )


def test_scan_edge_ssids() -> None:
    names = ["", "\\x00\\x00\\x00", "It\\xe2\\x80\\x99s", "a\\x5cb", "two words"]
    text = "".join(_bss(f"02:00:00:00:00:0{i}", s, 2412, -60) for i, s in enumerate(names, 1))
    assert [b.ssid for b in parse_scan(text)] == [None, None, "It’s", "a\\b", "two words"]


def test_scan_without_ht() -> None:
    [b] = parse_scan(_bss("02:00:00:00:00:01", "net", 2412, -60))
    assert (b.width_mhz, b.secondary) == (20, None)


def test_forty_below_spans() -> None:
    [b] = parse_scan(_bss("02:00:00:00:00:01", "wide", 2462, -50, secondary="below"))
    assert (b.channel, b.width_mhz, b.secondary) == (11, 40, "below")
    loads = channel_loads([], [], [b], range(1, 14))
    # 2462 MHz primary, secondary below: 2432-2472 MHz occupied, so channels 6 (2437) to 12 (2467)
    assert [c.channel for c in loads if c.networks] == [6, 7, 8, 9, 10, 11, 12]


def test_twenty_overlaps_its_neighbours() -> None:
    [b] = parse_scan(_bss("02:00:00:00:00:01", "n", 2437, -50))
    loads = channel_loads([], [], [b], range(1, 14))
    assert [c.channel for c in loads if c.networks] == [5, 6, 7]


def test_security_kinds() -> None:
    privacy = "ESS Privacy ShortSlotTime (0x0411)"
    text = (
        _bss("02:00:00:00:00:01", "a", 2412, -60, security=RSN_MIXED, capability=privacy)
        + _bss("02:00:00:00:00:02", "b", 2412, -60, security=RSN_SAE, capability=privacy)
        + _bss("02:00:00:00:00:03", "c", 2412, -60, security=WPA1, capability=privacy)
        + _bss("02:00:00:00:00:04", "d", 2412, -60, capability=privacy)
        + _bss("02:00:00:00:00:05", "e", 2412, -60)
    )
    assert [b.security for b in parse_scan(text)] == ["WPA2/WPA3", "WPA3", "WPA", "WEP", "open"]


def test_no_networks() -> None:
    assert parse_scan("") == []


def test_associated_marker_and_own() -> None:
    text = _bss("00:0C:43:76:20:18", "OwgTest", 2437, -30, head=" -- associated")
    [b] = parse_scan(text, own={"00:0c:43:76:20:18"})
    assert b.bssid == "00:0c:43:76:20:18" and b.own


def test_channel_of() -> None:
    assert [channel_of(f) for f in (2412, 2472, 2484, 5180, 5955, 2400)] == [1, 13, 14, 36, 1, None]
    assert freq_of(1) == 2412 and freq_of(13) == 2472 and freq_of(14) == 2484


def _survey(freq: int, active: int, busy: int) -> SurveyEntry:
    return SurveyEntry(freq_mhz=freq, in_use=True, noise_dbm=None, active_ms=active, busy_ms=busy)


def test_channel_loads() -> None:
    before = [_survey(2412, 1000, 500), _survey(2417, 2000, 100), _survey(2422, 3000, 3000)]
    after = [_survey(2412, 1110, 555), _survey(2417, 2000, 100), _survey(2422, 2000, 3000)]
    strong = parse_scan(_bss("02:00:00:00:00:01", "x", 2412, -40) + _bss("02:00:00:00:00:02", "y", 2412, -70))
    loads = {c.channel: c for c in channel_loads(before, after, strong, [1, 2, 3, 4])}
    assert loads[1].busy_pct == 50.0
    assert loads[2].busy_pct is None  # not visited by the scan
    assert loads[3].busy_pct is None  # a counter went backwards
    assert loads[4].busy_pct is None  # no survey entry at all
    assert (loads[1].networks, loads[1].strongest_dbm) == (2, -40.0)
    assert (loads[2].networks, loads[3].networks) == (2, 0)
    assert loads[1].freq_mhz == 2412
