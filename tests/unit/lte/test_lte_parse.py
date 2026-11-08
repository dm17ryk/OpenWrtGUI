"""lte/parse.py and lte/quality.py: uqmi JSON, AT answers and the signal quality labels."""

from __future__ import annotations

import pytest

from openwrtgui.lte.parse import (
    parse_at,
    parse_cops,
    parse_mode_order,
    parse_modem_info,
    parse_opmode,
    parse_serving,
    parse_signal,
)
from openwrtgui.lte.quality import label


def test_lte_signal() -> None:
    s = parse_signal('{"type":"lte","rssi":-67,"rsrq":-10,"rsrp":-95,"snr":8.2}')
    assert s is not None
    assert (s.type, s.rssi, s.rsrp, s.rsrq, s.snr) == ("lte", -67, -95, -10, 8.2)
    assert [label("rsrp", -95), label("rsrq", -10), label("snr", 8.2), label("rssi", -67)] == [
        "fair",
        "excellent",
        "fair",
        "good",
    ]


@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    [
        ("rsrp", -80, "excellent"),
        ("rsrp", -90, "good"),
        ("rsrp", -100, "fair"),
        ("rsrp", -100.5, "poor"),
        ("rsrq", -15, "good"),
        ("rsrq", -20.1, "poor"),
        ("snr", 20, "excellent"),
        ("snr", 0, "fair"),
        ("snr", -1, "poor"),
        ("rssi", -85, "fair"),
        ("rssi", -86, "poor"),
    ],
)
def test_label_boundaries_are_inclusive(metric: str, value: float, expected: str) -> None:
    assert label(metric, value) == expected  # type: ignore[arg-type]


def test_signal_of_other_radios() -> None:
    s = parse_signal('{"type":"umts","rssi":-80,"ecio":-7,"rscp":-90}')
    assert s is not None
    assert (s.type, s.rssi, s.ecio, s.rscp, s.rsrp, s.snr) == ("umts", -80, -7, -90, None, None)


def test_serving_system() -> None:
    s = parse_serving(
        '{"registration":"registered","radio_interface":["lte"],"roaming":false,'
        '"plmn_mcc":425,"plmn_mnc":1,"plmn_description":"Partner"}'
    )
    assert s is not None
    assert (s.registration, s.radio, s.roaming, s.mcc, s.mnc, s.qmi_name) == (
        "registered",
        "lte",
        False,
        425,
        1,
        "Partner",
    )


def test_serving_system_partial() -> None:
    s = parse_serving('{"registration":"searching"}')
    assert s is not None
    assert (s.registration, s.radio, s.roaming, s.mcc, s.qmi_name) == ("searching", None, None, None, None)


@pytest.mark.parametrize("text", ["", "Request canceled", "{", "[1,2]", '"online"'])
def test_garbage_is_no_answer(text: str) -> None:
    assert parse_signal(text) is None
    assert parse_serving(text) is None


def test_operating_mode() -> None:
    assert parse_opmode('"online"\n') == "online"
    assert parse_opmode("{}") is None
    assert parse_opmode("") is None


def test_at_answers() -> None:
    a = parse_at('AT+COPS?\r\r\n+COPS: 0,0,"Partner",7\r\n\r\nOK\r\n', "AT+COPS?")
    assert a is not None
    assert (a.status, a.lines, a.error) == ("OK", ('+COPS: 0,0,"Partner",7',), None)
    assert parse_cops(a.lines) == "Partner"
    err = parse_at("AT+X\r\r\n+CME ERROR: 100\r\n", "AT+X")
    assert err is not None and (err.status, err.error) == ("ERROR", "+CME ERROR: 100")
    plain = parse_at("\r\nERROR\r\n", "AT+Y")
    assert plain is not None and (plain.status, plain.error, plain.lines) == ("ERROR", "ERROR", ())
    assert parse_at("", "AT") is None  # silent port: no final status
    assert parse_at("AT+CSQ\r\r\n+CSQ: 20,99\r\n", "AT+CSQ") is None
    assert parse_mode_order(("+BMMODODR: 17",)) == 17
    assert parse_mode_order(("OK",)) is None
    assert parse_cops(("+COPS: 0",)) is None


def test_modem_info() -> None:
    echoed = (
        "AT+CGMI\r\r\nBroadMobi\r\n\r\nOK\r\nAT+CGMM\r\r\nBM806C\r\n\r\nOK\r\n"
        "AT+CGMR\r\r\nM1.2.0_E1.0.3_A1.1.8\r\n\r\nOK\r\n"
    )
    plain = "\r\n+CGMI: BroadMobi\r\n\r\nOK\r\n\r\nBM806C\r\n\r\nOK\r\n\r\nM1.2.0_E1.0.3_A1.1.8\r\n\r\nOK\r\n"
    expected = ("BroadMobi", "BM806C", "M1.2.0_E1.0.3_A1.1.8")
    assert parse_modem_info(echoed) == expected
    assert parse_modem_info(plain) == expected
    assert parse_modem_info("\r\nBroadMobi\r\n\r\nOK\r\n\r\nERROR\r\n") == ("BroadMobi", None, None)
    assert parse_modem_info("") == (None, None, None)
