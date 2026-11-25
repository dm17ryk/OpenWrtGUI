"""simmodem.py: the simulated BM806C (uqmi reads and writes, AT on ttyUSB2, ifup/ifdown lte)."""

from __future__ import annotations

import json

from openwrtgui.lte import commands as c
from openwrtgui.lte.sim import parse_sim_state
from openwrtgui.lte.sms import parse_cpms, parse_ids, parse_message
from openwrtgui.lte.ussd import parse_cusd
from openwrtgui.simmodem import SimModem
from openwrtgui.transport.base import CommandResult

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


AT = "/dev/ttyUSB2"


def _fails(modem: SimModem, command: str) -> CommandResult:
    answered = modem.answer(command)
    assert answered is not None and answered.exit_status == 1, command
    return answered


def test_sim_state_answers_ap2_shape() -> None:
    m = _modem()
    state = json.loads(_out(m, c.SIM_STATE(DEV)))
    assert state["pin1_status"] == "disabled" and state["pin1_unlock_tries"] == 10
    assert state["pin1_verify_tries"] == 3 and state["card_slot"] == 1
    parsed = parse_sim_state(_out(m, c.SIM_STATE(DEV)))
    assert parsed is not None and parsed.pin == "off" and parsed.puk_tries_left == 10
    status = json.loads(_out(m, c.PIN_STATUS(DEV)))
    assert status["pin1_unblock_tries"] == 10 and "pin1_unlock_tries" not in status
    m.pin1 = "not_verified"
    needed = parse_sim_state(_out(m, c.SIM_STATE(DEV)))
    assert needed is not None and needed.pin == "needed" and needed.can_enter_pin
    assert _out(m, c.at(AT, "AT+CPIN?")).endswith("+CPIN: SIM PIN\r\n\r\nOK\r\n")
    m.pin1 = "disabled"
    assert _out(m, c.at(AT, "AT+CPIN?")).endswith("+CPIN: READY\r\n\r\nOK\r\n")


def test_verify_pin_right_wrong_and_blocked() -> None:
    m = _modem()
    m.pin1 = "not_verified"
    _out(m, c.verify_pin1(DEV, "0000"))
    assert m.pin1 == "verified"
    m.pin1 = "not_verified"
    wrong = _fails(m, c.verify_pin1(DEV, "1234"))
    assert "1234" not in wrong.stderr and m.pin1_tries == 2 and m.pin1 == "not_verified"
    _fails(m, c.verify_pin1(DEV, "1234"))
    _fails(m, c.verify_pin1(DEV, "1234"))
    assert m.pin1_tries == 0 and m.pin1 == "blocked"
    _fails(m, c.verify_pin1(DEV, "0000"))
    assert m.pin1 == "blocked"
    blocked = parse_sim_state(_out(m, c.SIM_STATE(DEV)))
    assert blocked is not None and blocked.pin == "blocked"


def test_message_stores() -> None:
    m = _modem()
    assert parse_ids(_out(m, c.list_messages(DEV, "sim"))) == (0, 1, 2)
    assert parse_ids(_out(m, c.list_messages(DEV, "me"))) == ()
    msg = parse_message(_out(m, c.get_message(DEV, "sim", 1)), 1, "sim")
    assert msg is not None and msg.sender == "+15550102" and msg.text == "Test message 2"
    assert msg.time is not None
    _fails(m, c.get_message(DEV, "sim", 9))
    _out(m, c.delete_message(DEV, "sim", 1))
    assert parse_ids(_out(m, c.list_messages(DEV, "sim"))) == (0, 2)
    _fails(m, c.delete_message(DEV, "sim", 1))
    assert _out(m, c.at(AT, "AT+CPMS?")).endswith('+CPMS: "ME",0,23,"ME",0,23,"SM",2,20\r\n\r\nOK\r\n')


def test_cpms_follows_the_stores() -> None:
    m = _modem()
    lines = _out(m, c.at(AT, "AT+CPMS?")).splitlines()
    assert lines[2] == '+CPMS: "ME",0,23,"ME",0,23,"SM",3,20'
    assert parse_cpms(lines) == {"me": (0, 23), "sim": (3, 20)}


def test_send_message_records_the_unquoted_text() -> None:
    m = _modem()
    _out(m, c.send_message(DEV, "+15550104", 'It\'s a "test"'))
    assert m.sent == [("+15550104", 'It\'s a "test"')]


def test_ussd() -> None:
    m = _modem()
    out = _out(m, c.ussd(AT, "*100#"))
    lines = [line for line in out.splitlines() if line]
    assert lines[-2:] == ["OK", '+CUSD: 0,"Balance 12.34",15']
    assert parse_cusd(lines) == (0, "Balance 12.34", 15)
    more = [line for line in _out(m, c.ussd(AT, "*111#")).splitlines() if line]
    assert parse_cusd(more) == (1, "1 Balance 2 Packages", 15)
    ucs2 = [line for line in _out(m, c.ussd(AT, "*200#")).splitlines() if line]
    assert parse_cusd(ucs2) == (0, "05E905DC05D505DD", 72)
    unknown = _out(m, c.ussd(AT, "*999#"))
    assert "OK" in unknown and not any(line.startswith("+CUSD") for line in unknown.splitlines())
    assert _out(m, c.at(AT, c.USSD_CANCEL)).endswith("OK\r\n")


def test_ussd_on_a_silent_port_and_bmmododr_range() -> None:
    m = _modem()
    assert _out(m, c.ussd("/dev/ttyUSB0", "*100#")) == ""
    assert _out(m, c.at(AT, "AT+BMMODODR=?")).endswith("+BMMODODR: (2,3,17)\r\n\r\nOK\r\n")


def test_unplugged_modem() -> None:
    m = _modem()
    m.plugged = False
    for command in (c.SIGNAL(DEV), c.at("/dev/ttyUSB2", "AT"), c.TTY_LIST):
        answered = m.answer(command)
        assert answered is not None and answered.exit_status == 1, command
    assert m.answer("cat /etc/openwrt_release") is None  # not the modem's
