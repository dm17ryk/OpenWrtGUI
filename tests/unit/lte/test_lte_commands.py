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
