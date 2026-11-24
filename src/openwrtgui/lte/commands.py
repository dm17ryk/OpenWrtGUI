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
SIM_STATE = _read("--uim-get-sim-state")
PIN_STATUS = _read("--get-pin-status")

Storage = Literal["sim", "me"]
PIN_RULE = re.compile(r"[0-9]{4,8}")
TARGET_RULE = re.compile(r"\+?[0-9]{3,15}")
USSD_CODE = re.compile(r"[*#][0-9*#]{1,30}#")
PIN_MESSAGE = "A PIN is 4 to 8 digits"
TARGET_MESSAGE = "A number is digits with an optional + (3 to 15)"
USSD_MESSAGE = "A USSD code looks like *100#: * or #, digits, * or #, ending in #"

# the modem waits 30 s of silence for the network's answer; `timeout -s KILL` ends microcom at 35 s; the
# transport gives up at 45 s (v1.3b E8)
USSD_CANCEL = "AT+CUSD=2"
USSD_WAIT_S = 35
USSD_TIMEOUT_S = 45.0


def set_opmode(device: str, mode: Literal["low_power", "online"]) -> str:
    if mode not in ("low_power", "online"):
        raise ValueError("The modem is never set to reset: it wedges until a power cycle")
    return uqmi(device, "--set-device-operating-mode", mode, timeout_ms=3000)


def sync(device: str) -> str:
    """Release the client ids the modem still holds (stale QMI state). Sent only after `ifdown lte`, so it
    cannot release a live session's client (spec 4.2)."""
    return uqmi(device, "--sync", timeout_ms=5000)


def autoconnect_off(device: str) -> str:
    """QMI WDS Set Autoconnect Settings, disabled: what the stock firmware's "restore modem defaults" sends
    the BM806C (spec 4.9). It takes no value: the modem's own autoconnect fights the router's qmi.sh."""
    return uqmi(device, "--set-autoconnect", "disabled", timeout_ms=5000)


# uqmi's answer (exit 1) when QMI says the request changes nothing: for `autoconnect_off`, it is already off
# (AP2's BM806C, 2026-11-19 window: its qmi.sh turns autoconnect off at every connect)
NO_EFFECT = '"No effect"'

# How many uqmi processes run: qmi.sh's teardown releases its client with uqmi, and netifd's `ifdown lte`
# returns before it ends (AP2, 2026-11-19 window). `[u]` keeps grep from counting its own command line.
UQMI_RUNNING = "ps w | grep -c '[u]qmi '"
# #93: an LTE setup runs while netifd's qmi.sh (or a uqmi it started) is alive; cutting one off with
# `ifdown lte` left AP2's QMI channel failing until a router reboot (2026-11-19 window)
SETUP_RUNNING = "ps w | grep -c -e '[q]mi\\.sh' -e '[u]qmi '"


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
    """printf repeats its format for each argument: `printf '%s\\r' 'AT+CGMI' 'AT+CGMM'` sends both lines.

    `timeout -s KILL`: on a port that never takes the bytes (AP2's ttyUSB3) microcom waits in tcsetattr for
    the output to drain and only records SIGTERM, so a plain `timeout` never ends it (AP2, 2026-11-09)."""
    _checked(AT_PORT, port, "a serial port")
    args = " ".join(shell_quote(check_at(c)) for c in commands)
    return f"printf '%s\\r' {args} | timeout -s KILL 10 microcom -t 2000 -s 115200 {port}"


def _rule(rule: re.Pattern[str], value: str, message: str) -> str:
    if not rule.fullmatch(value):
        raise ValueError(message)
    return value


def verify_pin1(device: str, pin: str) -> str:
    return uqmi(device, "--verify-pin1", _rule(PIN_RULE, pin, PIN_MESSAGE), timeout_ms=5000)


def list_messages(device: str, storage: Storage) -> str:
    return uqmi(device, "--list-messages", "--storage", storage)


def get_message(device: str, storage: Storage, message_id: int) -> str:
    return uqmi(device, "--get-message", str(int(message_id)), "--storage", storage, timeout_ms=5000)


def delete_message(device: str, storage: Storage, message_id: int) -> str:
    return uqmi(device, "--delete-message", str(int(message_id)), "--storage", storage, timeout_ms=5000)


def send_message(device: str, target: str, text: str) -> str:
    _rule(TARGET_RULE, target, TARGET_MESSAGE)
    return uqmi(
        device, "--send-message", shell_quote(text), "--send-message-target", target, timeout_ms=10000
    )


def ussd(port: str, code: str) -> str:
    _checked(AT_PORT, port, "a serial port")
    command = shell_quote(f'AT+CUSD=1,"{_rule(USSD_CODE, code, USSD_MESSAGE)}",15')
    return f"printf '%s\\r' {command} | timeout -s KILL {USSD_WAIT_S} microcom -t 30000 -s 115200 {port}"
