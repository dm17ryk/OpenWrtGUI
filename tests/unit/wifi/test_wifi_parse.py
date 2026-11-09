from __future__ import annotations

from openwrtgui.wifi.parse import (
    IwDevInfo,
    IwIface,
    parse_beacon_rates,
    parse_freqlist,
    parse_ht_mcs,
    parse_iw_dev,
    parse_iw_dev_info,
    parse_phy_channels,
    parse_txpowerlist,
    parse_uci_show,
)

IW_INFO = (
    "Interface phy0-ap0\n\tifindex 12\n\twdev 0x1\n\taddr 02:11:22:33:44:55\n\tssid OpenWrt\n\ttype AP\n"
    "\twiphy 0\n\tchannel 6 (2437 MHz), width: 20 MHz, center1: 2437 MHz\n\ttxpower 20.00 dBm\n"
)
IW_INFO_NOHT = IW_INFO.replace("width: 20 MHz,", "width: 20 MHz (no HT),")
IW_INFO_HT40 = IW_INFO.replace("width: 20 MHz, center1: 2437 MHz", "width: 40 MHz, center1: 2447 MHz")
BEACONS = (
    "10:00:00.000001 6.0 Mb/s 2437 MHz 11g -38dBm signal antenna 0 Beacon (OpenWrt) "
    "[6.0* 9.0 12.0* 18.0 24.0* 36.0 48.0 54.0 Mbit] ESS CH: 6, PRIVACY\n"
    "10:00:00.102401 6.0 Mb/s 2437 MHz 11g -39dBm signal antenna 0 Beacon (OpenWrt) "
    "[6.0* 9.0 12.0* 18.0 24.0* 36.0 48.0 54.0 Mbit] ESS CH: 6, PRIVACY\n"
    "tcpdump: verbose output suppressed, use -v[v]... for full protocol decode\n"
)
IW_DEV = (
    "phy#0\n\tInterface owgmon0\n\t\tifindex 14\n\t\twdev 0x3\n\t\taddr 02:11:22:33:44:55\n\t\ttype monitor\n"
    "\tInterface phy0-ap0\n\t\tifindex 12\n\t\twdev 0x1\n\t\taddr 02:11:22:33:44:56\n\t\tssid OpenWrt\n"
    "\t\ttype AP\n\t\tchannel 6 (2437 MHz), width: 20 MHz, center1: 2437 MHz\n"
)


def test_iw_dev_info() -> None:
    assert parse_iw_dev_info(IW_INFO) == IwDevInfo(
        "phy0-ap0", 12, "02:11:22:33:44:55", "OpenWrt", "AP", 0, 6, 2437, 20, False, 20.0
    )


def test_no_ht_and_ht40() -> None:
    assert parse_iw_dev_info(IW_INFO_NOHT).no_ht
    assert parse_iw_dev_info(IW_INFO_NOHT).width_mhz == 20
    assert parse_iw_dev_info(IW_INFO_HT40).width_mhz == 40
    assert not parse_iw_dev_info(IW_INFO_HT40).no_ht


def test_iw_dev_info_missing_fields_are_none() -> None:
    info = parse_iw_dev_info("Interface phy0-ap0\n\ttype AP\n")
    assert info.ifname == "phy0-ap0" and info.channel is None and info.txpower_dbm is None


def test_ht_mcs() -> None:
    assert parse_ht_mcs("\t\tHT TX/RX MCS rate indexes supported: 0-15\n") == tuple(range(16))
    assert parse_ht_mcs("\t\tHT TX/RX MCS rate indexes supported: 0-7, 32\n") == (*range(8), 32)
    assert parse_ht_mcs("") == ()


PHY_INFO = (
    "Wiphy phy0\n\tBand 1:\n\t\tBitrates (non-HT):\n\t\t\t* 1.0 Mbps\n\t\t\t* 6.0 Mbps\n"
    "\t\tFrequencies:\n\t\t\t* 2412.0 MHz [1] (20.0 dBm)\n\t\t\t* 2437.0 MHz [6] (20.0 dBm)\n"
    "\t\t\t* 2467.0 MHz [12] (20.0 dBm) (no IR)\n\t\t\t* 2484.0 MHz [14] (disabled)\n"
    "\tvalid interface combinations:\n\t\t * #{ AP } <= 4, total <= 4, #channels <= 1\n"
)


def test_phy_channels_skip_disabled_and_no_ir() -> None:
    assert parse_phy_channels(PHY_INFO) == (1, 6)
    assert parse_phy_channels("") == ()


def test_freqlist_skips_restricted() -> None:
    result = {
        "results": [
            {"channel": 13, "mhz": 2472, "restricted": False},
            {"channel": 14, "mhz": 2484, "restricted": True},
        ]
    }
    assert parse_freqlist(result) == (13,)
    assert parse_freqlist({}) == ()


def test_txpowerlist() -> None:
    assert parse_txpowerlist({"results": [{"dbm": 0, "mw": 1}, {"dbm": 20, "mw": 100}]}) == (0, 20)


def test_beacons() -> None:
    assert parse_beacon_rates(BEACONS) == [6.0, 6.0]
    assert parse_beacon_rates("") == []


# AP2 (rt2800), 2026-11-05: its own beacons, seen on a monitor interface of the same radio, come from
# the TX path: the radiotap header has the rate and TX flags ([bit 15]) but no channel or signal.
OWN_BEACONS = (
    "23:45:08.773740 1.0 Mb/s [bit 15] BSSID:00:0c:43:76:20:18 DA:ff:ff:ff:ff:ff:ff SA:00:0c:43:76:20:18 "
    "Beacon (OwgTest) [1.0* 2.0* 5.5* 11.0* 6.0 9.0 12.0 18.0 Mbit] ESS CH: 6, PRIVACY\n"
    "23:45:09.388120 1.0 Mb/s [bit 15] 0us BSSID:00:0c:43:76:20:18 DA:ff:ff:ff:ff:ff:ff SA:00:0c:43:76:20:18 "
    "Beacon (OwgTest) [1.0* 2.0* 5.5* 11.0* 6.0 9.0 12.0 18.0 Mbit] ESS CH: 6, PRIVACY\n"
    "5 packets captured\n"
)


def test_own_beacons_seen_on_the_same_radio() -> None:
    assert parse_beacon_rates(OWN_BEACONS) == [1.0, 1.0]


def test_uci_show() -> None:
    text = (
        "wireless.radio0=wifi-device\n"
        "wireless.radio0.channel='1'\n"
        "wireless.radio0.channels='1' '6' '11'\n"
        "wireless.default_radio0.ssid='it'\\''s'\n"
    )
    assert parse_uci_show(text) == {
        "wireless.radio0": "wifi-device",
        "wireless.radio0.channel": "1",
        "wireless.radio0.channels": "1 6 11",
        "wireless.default_radio0.ssid": "it's",
    }


def test_iw_dev_lists_interfaces() -> None:
    assert parse_iw_dev(IW_DEV) == [
        IwIface("owgmon0", 0, "monitor", "02:11:22:33:44:55"),
        IwIface("phy0-ap0", 0, "AP", "02:11:22:33:44:56"),
    ]
    assert parse_iw_dev("") == []
