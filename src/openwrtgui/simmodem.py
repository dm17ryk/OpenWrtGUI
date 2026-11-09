"""A simulated BroadMobi BM806C for the router simulator: the uqmi reads and operating-mode writes the LTE
screen sends, AT on /dev/ttyUSB2 (ttyUSB0 and 1 are listed but silent, as a real modem's other ports are),
and `ifup lte` / `ifdown lte`, which SimNetwork reads back as the session state."""

from __future__ import annotations

import json
import random
import re
import shlex
from collections.abc import Callable

from openwrtgui.lte import commands as c
from openwrtgui.transport.base import CommandResult

DEVICE = "/dev/cdc-wdm0"
AT_PORT = "/dev/ttyUSB2"
PORTS = ("/dev/ttyUSB0", "/dev/ttyUSB1", AT_PORT)
IMEI = "353000000000001"
SERVING = {
    "registration": "registered",
    "radio_interface": ["lte"],
    "roaming": False,
    "plmn_mcc": 425,
    "plmn_mnc": 1,
    "plmn_description": "Partner",
}
SIGNAL: dict[str, float] = {"rssi": -67, "rsrq": -10, "rsrp": -95, "snr": 8.2}  # type "lte"
AT_ANSWERS = {
    "AT": (),
    "ATI": ("BroadMobi", "BM806C", "Revision: M1.2.0_E1.0.3_A1.1.8"),
    "AT+CGMI": ("BroadMobi",),
    "AT+CGMM": ("BM806C",),
    "AT+CGMR": ("M1.2.0_E1.0.3_A1.1.8",),
    "AT+COPS?": ('+COPS: 0,0,"Partner",7',),
    "AT+BMMODODR?": ("+BMMODODR: 17",),
    "AT+CSQ": ("+CSQ: 20,99",),
}
_MICROCOM = re.compile(
    r"printf '%s\\r' (.+) \| timeout -s KILL 10 microcom -t 2000 -s 115200 (/dev/ttyUSB[0-9])"
)
_SET_OPMODE = re.compile(
    re.escape(c.uqmi(DEVICE, "--set-device-operating-mode", "", timeout_ms=3000)) + r"(\w+)"
)


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult("", stdout, "", 0)


def _fail(stderr: str, status: int = 1) -> CommandResult:
    return CommandResult("", "", stderr, status)


class SimModem:
    def __init__(self, *, clock: Callable[[], float], seed: int = 806) -> None:
        self._clock = clock
        self._random = random.Random(seed)
        self.connected = True
        self.lease = True  # lte_4 holds an address while connected (AP2's real lte_4 waited for one)
        self.opmode = "online"
        self.plugged = True
        self.stays_low_power = False  # tests: the modem does not come back online
        self.rx_bytes = 1_204_331
        self.tx_bytes = 3_876_002

    def answer(self, command: str) -> CommandResult | None:
        if command in (c.IFUP_LTE, c.IFDOWN_LTE):
            self.connected = command == c.IFUP_LTE
            return _ok()
        if command == c.TTY_LIST:
            if not self.plugged:
                return _fail("ls: /dev/ttyUSB*: No such file or directory\n")
            return _ok("".join(f"{p}\n" for p in PORTS))
        if (m := _MICROCOM.fullmatch(command)) is not None:
            return self._at(m.group(2), shlex.split(m.group(1)))
        if command.startswith(f"uqmi -s -d {DEVICE} "):
            return self._uqmi(command)
        return None

    def _uqmi(self, command: str) -> CommandResult:
        if not self.plugged:
            return _fail("Failed to connect to service\n")
        if command == c.SERVING(DEVICE):
            return _ok(json.dumps(SERVING, separators=(",", ":")) + "\n")
        if command == c.SIGNAL(DEVICE):
            values: dict[str, object] = {"type": "lte"}
            for key, base in SIGNAL.items():
                value = base + self._random.randint(-3, 3)
                values[key] = round(value, 1) if key == "snr" else int(value)
            return _ok(json.dumps(values, separators=(",", ":")) + "\n")
        if command == c.OPMODE(DEVICE):
            return _ok(json.dumps(self.opmode) + "\n")
        if command == c.IMEI(DEVICE):
            return _ok(json.dumps(IMEI) + "\n")
        if (m := _SET_OPMODE.fullmatch(command)) is not None:
            mode = m.group(1)
            if not (mode == "online" and self.stays_low_power):
                self.opmode = mode
            return _ok()
        return _fail("Invalid argument\n")

    def _at(self, port: str, commands: list[str]) -> CommandResult:
        if not self.plugged:
            return _fail(f"microcom: can't open '{port}': No such file or directory\n")
        if port != AT_PORT:
            return _ok()  # a port that is not the AT port stays silent
        out: list[str] = []
        for command in commands:
            out.append(f"{command}\r\r\n")
            lines = AT_ANSWERS.get(command.upper())
            if lines is None and re.fullmatch(r"AT\+[A-Z]+=.*", command, re.IGNORECASE):
                lines = ()  # a setting the simulator accepts
            if lines is None:
                out.append("ERROR\r\n")
                continue
            out.extend(f"{line}\r\n\r\n" for line in lines)
            out.append("OK\r\n")
        return _ok("".join(out))
