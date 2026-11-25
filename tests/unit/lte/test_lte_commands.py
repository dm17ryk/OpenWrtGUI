"""lte/commands.py: the exact modem commands and the rules for what goes into them."""

from __future__ import annotations

import pytest

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.lte import commands as c

DEV = "/dev/cdc-wdm0"


def test_uqmi_reads() -> None:
    assert c.uqmi(DEV, "--get-signal-info") == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-signal-info"
    assert c.SERVING(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-serving-system"
    assert c.SIGNAL(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-signal-info"
    assert c.OPMODE(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-device-operating-mode"
    assert c.IMEI(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-imei"


def test_operating_mode_is_never_reset() -> None:
    assert c.set_opmode(DEV, "low_power") == (
        "uqmi -s -d /dev/cdc-wdm0 -t 3000 --set-device-operating-mode low_power"
    )
    assert c.set_opmode(DEV, "online").endswith("--set-device-operating-mode online")
    with pytest.raises(ValueError, match=r"^The modem is never set to reset: it wedges until a power cycle$"):
        c.set_opmode(DEV, "reset")  # type: ignore[arg-type]


def test_netifd_reads_and_writes() -> None:
    assert (c.IFUP_LTE, c.IFDOWN_LTE) == ("ifup lte", "ifdown lte")
    assert c.iface_status("lte_4") == "ubus call network.interface.lte_4 status"
    assert c.device_status("wwan0") == 'ubus call network.device status \'{"name":"wwan0"}\''
    assert c.TTY_LIST == "ls /dev/ttyUSB*"


MICROCOM = "timeout -s KILL 10 microcom -t 2000 -s 115200"


def test_at_commands_are_quoted_one_argument_each() -> None:
    assert c.at("/dev/ttyUSB2", "AT+COPS?") == f"printf '%s\\r' 'AT+COPS?' | {MICROCOM} /dev/ttyUSB2"
    assert c.at("/dev/ttyUSB2", "AT+CGMI", "AT+CGMM", "AT+CGMR") == (
        f"printf '%s\\r' 'AT+CGMI' 'AT+CGMM' 'AT+CGMR' | {MICROCOM} /dev/ttyUSB2"
    )
    quoted = "'AT+CGDCONT=1,\"IP\",\"a'\\''b\"'"
    assert (
        c.at("/dev/ttyUSB0", 'AT+CGDCONT=1,"IP","a\'b"')
        == f"printf '%s\\r' {quoted} | {MICROCOM} /dev/ttyUSB0"
    )


REFUSED = r"^An AT command is printable text starting with AT, at most 200 characters$"


@pytest.mark.parametrize("text", ["ATI\nreboot", "rm -rf /", "at" + "x" * 300, "AT\x07", ""])
def test_check_at_refuses(text: str) -> None:
    with pytest.raises(ValueError, match=REFUSED):
        c.check_at(text)


def test_check_at_strips_and_keeps_case() -> None:
    assert c.check_at("  at+csq  ") == "at+csq"
    assert c.check_at("AT" + "X" * 198) == "AT" + "X" * 198


@pytest.mark.parametrize(
    ("build", "value"),
    [
        (lambda v: c.uqmi(v, "--get-signal-info"), "/dev/cdc-wdm0;reboot"),
        (lambda v: c.at(v, "AT"), "/dev/ttyUSB10"),
        (c.device_status, "wwan0 x"),
        (c.iface_status, "lte;x"),
    ],
)
def test_argument_rules(build: object, value: str) -> None:
    with pytest.raises(ValueError):
        build(value)  # type: ignore[operator]


def test_reads_pass_the_read_only_check_and_writes_do_not() -> None:
    for read in (c.SERVING(DEV), c.SIGNAL(DEV), c.OPMODE(DEV), c.iface_status("lte"), c.TTY_LIST):
        assert is_read_only_command(read), read
    for write in (c.set_opmode(DEV, "online"), c.IFUP_LTE, c.IMEI(DEV)):
        assert not is_read_only_command(write), write


def test_sync_command_text() -> None:
    assert c.sync("/dev/cdc-wdm0") == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --sync"
    with pytest.raises(ValueError):
        c.sync("/dev/x")
    assert not is_read_only_command(c.sync(DEV))  # it releases client ids: never a background read


def test_autoconnect_off_command_text() -> None:
    """Spec 4.9: the stock restore-defaults (QMI WDS 0x0051, disabled). It takes no value."""
    assert c.autoconnect_off(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --set-autoconnect disabled"
    with pytest.raises(ValueError):
        c.autoconnect_off("/dev/x")
    assert not is_read_only_command(c.autoconnect_off(DEV))


def test_sim_reads_and_their_text() -> None:
    assert c.SIM_STATE(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --uim-get-sim-state"
    assert c.PIN_STATUS(DEV) == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --get-pin-status"
    assert c.list_messages(DEV, "me") == "uqmi -s -d /dev/cdc-wdm0 -t 2000 --list-messages --storage me"


def test_sms_and_pin_writes_text() -> None:
    assert c.verify_pin1(DEV, "1234") == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --verify-pin1 1234"
    assert c.get_message(DEV, "sim", 7) == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --get-message 7 --storage sim"
    assert (
        c.delete_message(DEV, "sim", 7) == "uqmi -s -d /dev/cdc-wdm0 -t 5000 --delete-message 7 --storage sim"
    )
    assert c.send_message(DEV, "+15550101", "it's ok") == (
        "uqmi -s -d /dev/cdc-wdm0 -t 10000 --send-message 'it'\\''s ok' --send-message-target +15550101"
    )


def test_ussd_waits_30_s_of_silence_and_is_killed_at_35() -> None:
    assert c.ussd("/dev/ttyUSB1", "*100#") == (
        "printf '%s\\r' 'AT+CUSD=1,\"*100#\",15' | "
        "timeout -s KILL 35 microcom -t 30000 -s 115200 /dev/ttyUSB1"
    )
    assert c.ussd_request("*100#") == 'AT+CUSD=1,"*100#",15'  # the AT text alone (P10)
    assert c.USSD_CANCEL == "AT+CUSD=2"
    assert c.USSD_WAIT_S == 35
    assert c.USSD_TIMEOUT_S == 45.0


@pytest.mark.parametrize("bad", ["123", "123456789", "12a4", " 1234", ""])
def test_a_pin_is_4_to_8_digits(bad: str) -> None:
    with pytest.raises(ValueError, match="A PIN is 4 to 8 digits"):
        c.verify_pin1(DEV, bad)


@pytest.mark.parametrize("bad", ["12", "+12a4567", "1" * 16, ""])
def test_a_target_is_digits_with_an_optional_plus(bad: str) -> None:
    with pytest.raises(ValueError, match=r"A number is digits with an optional \+ \(3 to 15\)"):
        c.send_message(DEV, bad, "x")


@pytest.mark.parametrize("bad", ["100#", "*100", "*10;0#", "*" + "1" * 31 + "#"])
def test_a_ussd_code_is_star_or_hash_digits_and_hash(bad: str) -> None:
    with pytest.raises(ValueError, match=r"A USSD code looks like \*100#"):
        c.ussd("/dev/ttyUSB1", bad)
    with pytest.raises(ValueError, match=r"A USSD code looks like \*100#"):
        c.ussd_request(bad)


def test_reads_are_read_only_and_writes_are_not() -> None:
    for read in (
        c.SIM_STATE(DEV),
        c.PIN_STATUS(DEV),
        c.list_messages(DEV, "sim"),
        c.list_messages(DEV, "me"),
    ):
        assert is_read_only_command(read), read
    for write in (
        c.verify_pin1(DEV, "1234"),
        c.get_message(DEV, "sim", 1),
        c.delete_message(DEV, "sim", 1),
        c.send_message(DEV, "+15550101", "x"),
        c.ussd("/dev/ttyUSB1", "*100#"),
    ):
        assert not is_read_only_command(write), write
