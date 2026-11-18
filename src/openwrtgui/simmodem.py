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
_SYNC = c.uqmi(DEVICE, "--sync", timeout_ms=5000)
_AUTOCONNECT_OFF = c.uqmi(DEVICE, "--set-autoconnect", "disabled", timeout_ms=5000)
HANDLE = {"cid_4": "11", "pdh_4": "90215808"}  # AP2's recorded lte status: a live session's handle
NO_HANDLE = {"pdh_4": "0xffffffff"}  # a wedged BM806C: the session is up but carries no data


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
        self.wedged = False  # tests: ifup brings the session up without a packet-data handle until a restart
        self.stale_qmi = False  # tests: ifup starts no session until `uqmi --sync` releases the client ids
        # tests: the modem's own autoconnect holds the bearer (qmi.sh's unchecked attempt to turn it off at
        # ifup did not take); `--set-autoconnect disabled` clears it after `autoconnect_refusals` failures
        self.autoconnect_on = False
        self.autoconnect_refusals = 0
        self._low_power_seen = False
        self.rx_bytes = 1_204_331
        self.tx_bytes = 3_876_002

    def answer(self, command: str) -> CommandResult | None:
        if command in (c.IFUP_LTE, c.IFDOWN_LTE):
            blocked = self.stale_qmi or self.autoconnect_on
            self.connected = command == c.IFUP_LTE and not blocked  # netifd's ifup exits 0 either way
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
        if command == _SYNC:
            self.stale_qmi = False
            return _ok()
        if command == _AUTOCONNECT_OFF:
            if self.autoconnect_refusals > 0:
                self.autoconnect_refusals -= 1
                return _fail("Request failed\n")
            self.autoconnect_on = False
            return _ok()
        if (m := _SET_OPMODE.fullmatch(command)) is not None:
            mode = m.group(1)
            if not (mode == "online" and self.stays_low_power):
                self.opmode = mode
            if mode == "low_power":
                self._low_power_seen = True
            elif self.opmode == "online" and self._low_power_seen:
                self.wedged = self._low_power_seen = False  # a low_power, online cycle restarts the modem
            return _ok()
        return _fail("Invalid argument\n")

    def netifd_restart(self) -> None:
        """netifd restarts an interface whose config changed (a network reload): the session comes back unless
        a fault keeps it down."""
        self.connected = not (self.stale_qmi or self.autoconnect_on)

    def session_data(self) -> dict[str, str]:
        """The `data` entry of the lte interface's status while its session is up."""
        return dict(NO_HANDLE if self.wedged else HANDLE)

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
