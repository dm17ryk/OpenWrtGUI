"""simmodem.py: the simulated BM806C (uqmi reads and writes, AT on ttyUSB2, ifup/ifdown lte)."""

from __future__ import annotations

import json

from openwrtgui.lte import commands as c
from openwrtgui.simmodem import SimModem

DEV = "/dev/cdc-wdm0"


def _modem() -> SimModem:
    return SimModem(clock=lambda: 0.0)


def _out(modem: SimModem, command: str) -> str:
    answered = modem.answer(command)
    assert answered is not None and answered.exit_status == 0, command
    return answered.stdout


def test_uqmi_answers() -> None:
    m = _modem()
    serving = json.loads(_out(m, c.SERVING(DEV)))
    assert serving == {
        "registration": "registered",
        "radio_interface": ["lte"],
        "roaming": False,
        "plmn_mcc": 425,
        "plmn_mnc": 1,
        "plmn_description": "Partner",
    }
    for _ in range(20):
        signal = json.loads(_out(m, c.SIGNAL(DEV)))
        assert signal["type"] == "lte"
        assert -70 <= signal["rssi"] <= -64 and -98 <= signal["rsrp"] <= -92
        assert -13 <= signal["rsrq"] <= -7 and 5.2 <= signal["snr"] <= 11.2
    assert json.loads(_out(m, c.OPMODE(DEV))) == "online"
    assert json.loads(_out(m, c.IMEI(DEV))) == "353000000000001"


def test_operating_mode_follows_the_writes() -> None:
    m = _modem()
    _out(m, c.set_opmode(DEV, "low_power"))
    assert json.loads(_out(m, c.OPMODE(DEV))) == "low_power"
    m.stays_low_power = True
    _out(m, c.set_opmode(DEV, "online"))
    assert json.loads(_out(m, c.OPMODE(DEV))) == "low_power"


def test_at_on_ttyusb2_only() -> None:
    m = _modem()
    assert _out(m, c.TTY_LIST) == "/dev/ttyUSB0\n/dev/ttyUSB1\n/dev/ttyUSB2\n"
    assert _out(m, c.at("/dev/ttyUSB0", "AT")) == ""
    assert _out(m, c.at("/dev/ttyUSB2", "AT")) == "AT\r\r\nOK\r\n"
    assert _out(m, c.at("/dev/ttyUSB2", "AT+COPS?")) == 'AT+COPS?\r\r\n+COPS: 0,0,"Partner",7\r\n\r\nOK\r\n'
    info = _out(m, c.at("/dev/ttyUSB2", "AT+CGMI", "AT+CGMM", "AT+CGMR"))
    assert "BroadMobi" in info and "BM806C" in info and "M1.2.0_E1.0.3_A1.1.8" in info
    assert info.count("OK") == 3
    assert _out(m, c.at("/dev/ttyUSB2", "AT+BMMODODR?")).endswith("+BMMODODR: 17\r\n\r\nOK\r\n")
    assert _out(m, c.at("/dev/ttyUSB2", "AT+CSQ")).endswith("+CSQ: 20,99\r\n\r\nOK\r\n")
    assert _out(m, c.at("/dev/ttyUSB2", "AT+CFUN=1")).endswith("\r\nOK\r\n")
    assert _out(m, c.at("/dev/ttyUSB2", "ATZZ")).endswith("\r\nERROR\r\n")


def test_unplugged_modem() -> None:
    m = _modem()
    m.plugged = False
    for command in (c.SIGNAL(DEV), c.at("/dev/ttyUSB2", "AT"), c.TTY_LIST):
        answered = m.answer(command)
        assert answered is not None and answered.exit_status == 1, command
    assert m.answer("cat /etc/openwrt_release") is None  # not the modem's
