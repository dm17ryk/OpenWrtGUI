"""Frame analysis: tcpdump lines from the monitor interface and the window summary (v0.7 plan Task 5)."""

from __future__ import annotations

import json
from pathlib import Path

from openwrtgui.rf.frames import Direction, Frame, FrameWindow, combine, parse_frame, summarize

OWN = "00:0c:43:76:20:18"
STA = "aa:bb:cc:dd:ee:01"
RX_LINE = (
    "23:54:52.943020 1234567890us tsft short preamble 54.0 Mb/s 2437 MHz 11g -52dBm signal antenna 0 "
    f"Retry 44us BSSID:{OWN} SA:{STA} DA:{OWN} Data IV:  1 Pad 0 KeyID 0"
)
TX_LINE = (
    "23:54:52.950000 65.0 Mb/s MCS 7 20 MHz short GI antenna 0 "
    f"44us DA:{STA} BSSID:{OWN} SA:{OWN} QoS Data IV:  2 Pad 0 KeyID 0"
)
BAD_LINE = (
    "23:54:52.960000 bad-fcs 1.0 Mb/s 2437 MHz 11b -88dBm signal antenna 0 "
    "BSSID:02:00:00:00:00:09 DA:ff:ff:ff:ff:ff:ff SA:02:00:00:00:00:09 Beacon (net-09)"
)
OTHER_LINE = (
    "23:54:52.970000 6.0 Mb/s 2437 MHz 11g -70dBm signal antenna 0 "
    "BSSID:02:00:00:00:00:05 SA:02:00:00:00:00:06 DA:02:00:00:00:00:05 Data IV"
)
WIFI_ON = Path(__file__).resolve().parents[2] / "fixtures" / "ap2" / "wifi_on.json"


def test_rx_data_frame() -> None:
    frame = parse_frame(RX_LINE)
    assert frame == Frame(rate="54.0", signal_dbm=-52, bad_fcs=False, retry=True, src=STA, bssid=OWN, dst=OWN)
    window = summarize(RX_LINE, "", {OWN}, 3.0)
    assert (window.rx.frames, window.rx.retries, window.rx.rates, window.tx.frames) == (1, 1, {"54.0": 1}, 0)


def test_tx_mcs_frame() -> None:
    frame = parse_frame(TX_LINE)
    assert frame is not None and frame.rate == "MCS 7" and frame.signal_dbm is None and not frame.retry
    window = summarize(TX_LINE, "", {OWN}, 3.0)
    assert (window.tx.frames, window.tx.rates, window.rx.frames) == (1, {"MCS 7": 1}, 0)


def test_bad_fcs_counts_only_in_totals() -> None:
    window = summarize(BAD_LINE + "\n" + OTHER_LINE, "", {OWN}, 3.0)
    assert (window.frames, window.bad_fcs, window.rx.frames, window.tx.frames) == (2, 1, 0, 0)


def test_beacon_from_tx_path() -> None:
    recorded = json.loads(WIFI_ON.read_text(encoding="utf-8"))
    capture = next(v["stdout"] for k, v in recorded.items() if k.startswith("timeout 5 tcpdump"))
    window = summarize(capture, "", {OWN}, 5.0)
    assert window.tx.frames == 5 and window.tx.rates == {"6.0": 5} and window.tx.signal_hist == {}


def test_signal_bins() -> None:
    lines = "\n".join(RX_LINE.replace("-52dBm", f"{s}dBm") for s in (-46, -50, -51))
    assert summarize(lines, "", {OWN}, 3.0).rx.signal_hist == {-50: 2, -55: 1}


def test_window_edge_cases() -> None:
    empty = summarize("", "", {OWN}, 3.0)
    assert (empty.frames, empty.bad_fcs, empty.dropped) == (0, 0, None)
    only_bad = summarize(BAD_LINE + "\n" + BAD_LINE, "", {OWN}, 3.0)
    assert only_bad.bad_fcs == only_bad.frames == 2 and only_bad.rx.frames == only_bad.tx.frames == 0
    odd = RX_LINE.replace("antenna 0", "antenna 0 he-mu-other 7 future-field 9")
    assert summarize(odd, "", {OWN}, 3.0).rx.frames == 1
    stderr = "2 packets captured\n2 packets received by filter\n0 packets dropped by kernel\n"
    assert summarize(RX_LINE, stderr, {OWN}, 3.0).dropped == 0
    listening = "listening on owgmon0, link-type IEEE802_11_RADIO (802.11 plus radiotap header)"
    assert parse_frame(listening) is None
    assert parse_frame("") is None


def test_combine_adds() -> None:
    a = summarize(RX_LINE + "\n" + TX_LINE, "0 packets dropped by kernel", {OWN}, 3.0)
    b = summarize(RX_LINE + "\n" + BAD_LINE, "3 packets dropped by kernel", {OWN}, 3.0)
    total = combine(a, b)
    assert total == FrameWindow(
        seconds=6.0,
        frames=4,
        bad_fcs=1,
        rx=Direction(frames=2, retries=2, rates={"54.0": 2}, signal_hist={-55: 2}),
        tx=Direction(frames=1, retries=0, rates={"MCS 7": 1}, signal_hist={}),
        dropped=3,
    )
