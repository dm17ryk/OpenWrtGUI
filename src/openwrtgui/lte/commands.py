"""The exact commands the LTE screen sends (v0.6a plan, "LTE rules"). Every value put into one is checked with
`re.fullmatch` first; AT text is shell-quoted, one printf argument per command."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from openwrtgui.uci import shell_quote

MODEM_DEVICE = re.compile(r"/dev/cdc-wdm[0-9]")
AT_PORT = re.compile(r"/dev/ttyUSB[0-9]")
NETDEV = re.compile(r"[A-Za-z0-9._-]{1,15}")
IFACE = re.compile(r"[A-Za-z0-9_]{1,15}")
AT_TEXT = re.compile(r"AT[\x20-\x7e]{0,198}", re.IGNORECASE)
AT_MESSAGE = "An AT command is printable text starting with AT, at most 200 characters"

IFUP_LTE = "ifup lte"
IFDOWN_LTE = "ifdown lte"
TTY_LIST = "ls /dev/ttyUSB*"


def _checked(rule: re.Pattern[str], value: str, what: str) -> str:
    if not rule.fullmatch(value):
        raise ValueError(f"{value!r} is not {what}")
    return value


def uqmi(device: str, *args: str, timeout_ms: int = 2000) -> str:
    _checked(MODEM_DEVICE, device, "a QMI modem device")
    return " ".join(("uqmi", "-s", "-d", device, "-t", str(timeout_ms), *args))


def _read(option: str) -> Callable[[str], str]:
    return lambda device: uqmi(device, option)


SERVING = _read("--get-serving-system")
SIGNAL = _read("--get-signal-info")
OPMODE = _read("--get-device-operating-mode")
IMEI = _read("--get-imei")


def set_opmode(device: str, mode: Literal["low_power", "online"]) -> str:
    if mode not in ("low_power", "online"):
        raise ValueError("The modem is never set to reset: it wedges until a power cycle")
    return uqmi(device, "--set-device-operating-mode", mode, timeout_ms=3000)


def iface_status(name: str) -> str:
    return f"ubus call network.interface.{_checked(IFACE, name, 'an interface name')} status"


def device_status(netdev: str) -> str:
    name = _checked(NETDEV, netdev, "a network device name")
    return f'ubus call network.device status \'{{"name":"{name}"}}\''


def check_at(text: str) -> str:
    stripped = text.strip()
    if not AT_TEXT.fullmatch(stripped):
        raise ValueError(AT_MESSAGE)
    return stripped


def at(port: str, *commands: str) -> str:
    """printf repeats its format for each argument: `printf '%s\\r' 'AT+CGMI' 'AT+CGMM'` sends both lines."""
    _checked(AT_PORT, port, "a serial port")
    args = " ".join(shell_quote(check_at(c)) for c in commands)
    return f"printf '%s\\r' {args} | timeout 10 microcom -t 2000 -s 115200 {port}"
