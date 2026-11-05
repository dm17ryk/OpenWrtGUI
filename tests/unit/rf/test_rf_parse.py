from __future__ import annotations

from openwrtgui.rf.parse import Bitrate, parse_bitrate, parse_station_dump, parse_survey, split_sections

# Formats as AP2 prints them (txlab_4b_rx tests, 2026-10-25).
STA = """Station 7c:df:a1:e8:ca:08 (on phy0-ap0)
\tinactive time:\t20 ms
\trx bytes:\t5000
\trx packets:\t100
\ttx bytes:\t90000
\ttx packets:\t1000
\ttx retries:\t50
\ttx failed:\t1
\trx drop misc:\t0
\tsignal:  \t-47 [-49, -50] dBm
\tsignal avg:\t-48 [-50, -51] dBm
\ttx bitrate:\t65.0 MBit/s MCS 7
\trx bitrate:\t54.0 MBit/s
\texpected throughput:\t38.0Mbps
\tconnected time:\t30 seconds
Station f4:12:fa:f3:57:68 (on phy0-ap0)
\tinactive time:\t1200 ms
\tsignal:  \t-70 dBm
\ttx bitrate:\t1.0 MBit/s
"""
SURVEY_RT2800 = """Survey data from phy0-ap0
\tfrequency:\t2437 MHz [in use]
\tchannel active time:\t1000 ms
\tchannel busy time:\t200 ms
Survey data from phy0-ap0
\tfrequency:\t2412 MHz
"""


def test_bitrates() -> None:
    assert parse_bitrate("65.0 MBit/s MCS 7") == Bitrate(65.0, 7, 20, False, "n20")
    assert parse_bitrate("150.0 MBit/s MCS 7 40MHz short GI") == Bitrate(150.0, 7, 40, True, "n40")
    assert parse_bitrate("54.0 MBit/s") == Bitrate(54.0, None, 20, False, "g")
    assert parse_bitrate("5.5 MBit/s") == Bitrate(5.5, None, 20, False, "b")
    assert parse_bitrate("") is None


def test_station_dump() -> None:
    first, second = parse_station_dump(STA)
    assert first.mac == "7c:df:a1:e8:ca:08" and first.tx_packets == 1000 and first.tx_retries == 50
    assert first.signal_dbm == -47 and first.chains == (-49, -50) and first.signal_avg_dbm == -48
    assert first.tx == Bitrate(65.0, 7, 20, False, "n20") and first.rx == Bitrate(54.0, None, 20, False, "g")
    assert first.expected_mbps == 38.0 and first.connected_s == 30 and first.ack_signal_dbm is None
    assert second.mac == "f4:12:fa:f3:57:68" and second.chains == () and second.tx_packets is None
    assert parse_station_dump("") == [] and parse_station_dump("Station not found") == []


def test_survey_without_noise_on_rt2800() -> None:
    in_use, other = parse_survey(SURVEY_RT2800)
    assert in_use.in_use and in_use.freq_mhz == 2437 and in_use.noise_dbm is None
    assert (in_use.active_ms, in_use.busy_ms) == (1000, 200)
    assert not other.in_use and other.active_ms is None


def test_survey_with_noise() -> None:
    [entry] = parse_survey("Survey data from x\n\tfrequency:\t2412 MHz [in use]\n\tnoise:\t-92 dBm\n")
    assert entry.noise_dbm == -92


def test_split_sections() -> None:
    sections = split_sections("===STA\nx\ny\n===ACK\n12\n===INFO\n\ttxpower 4.00 dBm\n")
    assert sections == {"STA": "x\ny", "ACK": "12", "INFO": "\ttxpower 4.00 dBm"}
    assert split_sections("") == {}
