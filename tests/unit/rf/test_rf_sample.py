from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from openwrtgui.rf.parse import Bitrate, StationRaw, SurveyEntry
from openwrtgui.rf.sample import RawTick, derive, rf_command
from openwrtgui.wifi.parse import IwDevInfo

T0 = datetime(2026, 11, 5, 9, 0, 0)
INFO = IwDevInfo("phy0-ap0", 12, "02:00:00:00:00:01", "OpenWrt", "AP", 0, 6, 2437, 20, False, 20.0)


def _sta(mac: str = "f4:12:fa:f3:57:68", **kw: object) -> StationRaw:
    base = StationRaw(
        mac=mac,
        inactive_ms=40,
        rx_bytes=10_000,
        rx_packets=100,
        tx_bytes=50_000,
        tx_packets=1000,
        tx_retries=50,
        tx_failed=1,
        rx_drop_misc=0,
        signal_dbm=-52,
        chains=(-54, -55),
        signal_avg_dbm=-53,
        avg_chains=(-55, -56),
        tx=Bitrate(65.0, 7, 20, False, "n20"),
        rx=Bitrate(54.0, None, 20, False, "g"),
        expected_mbps=38.0,
        ack_signal_dbm=None,
        connected_s=100,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def _tick(at: datetime, stations: tuple[StationRaw, ...], active: int, busy: int, ack: int | None) -> RawTick:
    return RawTick(at, stations, SurveyEntry(2437, True, None, active, busy), ack, INFO)


def test_rf_command() -> None:
    assert rf_command("phy0-ap0", "phy0") == (
        "echo ===STA; iw dev phy0-ap0 station dump; echo ===SURVEY; iw dev phy0-ap0 survey dump; "
        "echo ===ACK; cat /sys/kernel/debug/ieee80211/phy0/statistics/dot11ACKFailureCount 2>/dev/null; "
        "echo ===INFO; iw dev phy0-ap0 info"
    )


def test_first_tick_has_no_rates() -> None:
    sample = derive(None, _tick(T0, (_sta(),), 1000, 200, 10), "ap1", "radio0", {})
    radio = sample.radio_sample
    assert (radio.channel, radio.freq_mhz, radio.width_mhz, radio.txpower_dbm) == (6, 2437, 20, 20.0)
    assert radio.busy_pct is None and radio.ack_fail_per_s is None and radio.noise_dbm is None
    [sta] = sample.stations
    assert sta.signal_dbm == -52 and sta.chains == (-54, -55) and sta.retry_pct is None and sta.tx_pps is None


def test_derive_rates_and_busy() -> None:
    prev = _tick(T0, (_sta(),), 1000, 200, 10)
    cur = _tick(
        T0 + timedelta(seconds=1),
        (
            _sta(
                tx_packets=1750,
                tx_retries=125,
                tx_failed=4,
                rx_packets=300,
                rx_bytes=35_000,
                tx_bytes=150_000,
            ),
        ),
        7000,
        1400,
        13,
    )
    sample = derive(prev, cur, "ap1", "radio0", {"f4:12:fa:f3:57:68": "panel"})
    assert sample.radio_sample.busy_pct == 20.0 and sample.radio_sample.ack_fail_per_s == 3.0
    [sta] = sample.stations
    assert sta.name == "panel" and sta.retry_pct == 10.0 and sta.failed_per_s == 3.0
    assert sta.tx_pps == 750.0 and sta.rx_pps == 200.0 and sta.rx_kbps == 200.0 and sta.tx_kbps == 800.0


def test_station_leaving_is_marked_left() -> None:
    prev = _tick(T0, (_sta(), _sta("aa:bb:cc:dd:ee:ff")), 1000, 200, 10)
    cur = _tick(T0 + timedelta(seconds=1), (_sta(),), 2000, 300, 11)
    sample = derive(prev, cur, "ap1", "radio0", {})
    assert sample.left == ("aa:bb:cc:dd:ee:ff",) and [s.mac for s in sample.stations] == ["f4:12:fa:f3:57:68"]


def test_counter_reset_gives_none() -> None:
    prev = _tick(T0, (_sta(tx_packets=5000),), 1000, 200, 10)
    cur = _tick(T0 + timedelta(seconds=1), (_sta(tx_packets=10),), 500, 100, 2)
    sample = derive(prev, cur, "ap1", "radio0", {})
    assert sample.stations[0].tx_pps is None and sample.stations[0].retry_pct is None
    assert sample.radio_sample.busy_pct is None and sample.radio_sample.ack_fail_per_s is None
