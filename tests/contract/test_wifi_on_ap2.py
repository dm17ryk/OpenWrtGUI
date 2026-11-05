"""The RF and verify parsers against AP2 on air (OwgTest, channel 6, n20; recorded 2026-11-05, no station)."""

from pathlib import Path

from openwrtgui.rf.parse import current_survey, parse_station_dump, parse_survey
from openwrtgui.transport.fake import load_commands
from openwrtgui.wifi.parse import parse_beacon_rates, parse_ht_mcs, parse_iw_dev_info

ON = load_commands(Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "wifi_on.json")
BEACONS = (
    "timeout 5 tcpdump -i owgmon0 -e -n -c 5 -l 'type mgt subtype beacon and wlan addr2 00:0c:43:76:20:18'"
)


def test_iw_dev_info_on_air() -> None:
    info = parse_iw_dev_info(ON["iw dev phy0-ap0 info"].stdout)
    assert (info.ifname, info.type, info.ssid, info.addr) == (
        "phy0-ap0",
        "AP",
        "OwgTest",
        "00:0c:43:76:20:18",
    )
    assert (info.channel, info.freq_mhz, info.width_mhz, info.no_ht) == (6, 2437, 20, False)
    assert info.txpower_dbm == 20.0


def test_no_station_joined() -> None:
    assert parse_station_dump(ON["iw dev phy0-ap0 station dump"].stdout) == []


def test_survey_o4_no_noise_and_every_channel_in_use() -> None:
    entries = parse_survey(ON["iw dev phy0-ap0 survey dump"].stdout)
    assert [e.freq_mhz for e in entries] == [2407 + 5 * ch for ch in range(1, 14)]
    assert all(e.in_use for e in entries) and all(e.noise_dbm is None for e in entries)
    own = current_survey(entries, 2437)
    assert own is not None and own.active_ms and own.busy_ms is not None and own.busy_ms <= own.active_ms


def test_own_beacons_at_the_lowest_basic_rate() -> None:
    assert parse_beacon_rates(ON[BEACONS].stdout) == [6.0] * 5


def test_ack_failure_counter_and_mcs() -> None:
    ack = ON["cat /sys/kernel/debug/ieee80211/phy0/statistics/dot11ACKFailureCount"].stdout.strip()
    assert ack.isdigit()
    assert parse_ht_mcs(ON["iw phy phy0 info"].stdout) == (*range(16), 32)
