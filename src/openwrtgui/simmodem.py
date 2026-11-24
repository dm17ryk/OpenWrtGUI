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
        # tests: netifd's `ifdown lte` returns while qmi.sh's teardown still runs uqmi (AP2, 2026-11-19): the
        # next `teardown_reads` reads of the running uqmi count show one. A `--sync` sent meanwhile takes the
        # modem's QMI service down: no session starts again, a modem restart does not help (sync_raced).
        self.teardown_reads = 0
        self._tearing = 0
        self.sync_raced = False
        # tests (#93): after `ifup lte`, netifd's qmi.sh setup runs uqmi for the next `setup_reads` reads of
        # the running counts. On a link that cannot connect, netifd retries the setup after `retry_gap` idle
        # reads (0: the setup never pauses). An `ifdown lte` or a network reload during a setup leaves the
        # modem's QMI channel failing (setup_cut): no session starts again; a modem restart does not help.
        self.setup_reads = 0
        self.retry_gap = 0
        self.setup_cut = False
        self._setup_left = 0
        self._gap_left = 0
        self._retry_next = False
        self._low_power_seen = False
        self.rx_bytes = 1_204_331
        self.tx_bytes = 3_876_002

    def answer(self, command: str) -> CommandResult | None:
        if command in (c.IFUP_LTE, c.IFDOWN_LTE):
            if command == c.IFDOWN_LTE and self.setup_running():
                self.setup_cut = True
            self.connected = command == c.IFUP_LTE and not self._blocked()  # netifd's ifup exits 0 either way
            self._tearing = self.teardown_reads if command == c.IFDOWN_LTE else 0
            if command == c.IFUP_LTE:
                self.start_setup()
            else:  # netifd stops retrying a link it took down
                self._setup_left = self._gap_left = 0
                self._retry_next = False
            return _ok()
        if command in (c.UQMI_RUNNING, c.SETUP_RUNNING):
            running = 1 if self._setup_read() or self._tearing > 0 else 0
            self._tearing = max(0, self._tearing - 1)
            return CommandResult("", f"{running}\n", "", 0 if running else 1)  # grep -c exits 1 on none
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
            self.sync_raced = self.sync_raced or self._tearing > 0
            self.stale_qmi = False
            return _ok()
        if command == _AUTOCONNECT_OFF:
            if self.autoconnect_refusals > 0:
                self.autoconnect_refusals -= 1
                return _fail("Request failed\n")
            if not self.autoconnect_on:  # AP2's BM806C, 2026-11-19: the setting is already off
                return CommandResult("", f"{c.NO_EFFECT}\n", "", 1)
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

    def _blocked(self) -> bool:
        """A fault that keeps any session from starting."""
        return self.stale_qmi or self.autoconnect_on or self.sync_raced or self.setup_cut

    def start_setup(self) -> None:
        """netifd starts qmi.sh's setup now (an ifup, a retry, a reload). Tests use it to place a job inside a
        retry."""
        self._setup_left, self._gap_left, self._retry_next = self.setup_reads, 0, False

    def setup_running(self) -> bool:
        return self._setup_left > 0

    def _setup_read(self) -> bool:
        """One read of a running count: a setup advances by one read; on a failing link netifd retries after
        its gap (at once when the gap is 0, so the setup never pauses). A retry starts at the read after the
        gap's last, so a command sent right after an idle read lands in the gap."""
        if self._retry_next:
            self._retry_next = False
            self._setup_left = self.setup_reads
        if self._setup_left > 0:
            self._setup_left -= 1
            if self._setup_left == 0 and self._blocked():
                self._gap_left = self.retry_gap
                if self.retry_gap == 0:
                    self._setup_left = self.setup_reads
            return True
        if self._gap_left > 0:
            self._gap_left -= 1
            self._retry_next = self._gap_left == 0 and self._blocked()
        return False

    def netifd_restart(self) -> None:
        """netifd restarts an interface whose config changed (a network reload): the session comes back unless
        a fault keeps it down. A setup it cuts off wedges QMI as an `ifdown lte` does (#93)."""
        if self.setup_running():
            self.setup_cut = True
        self.connected = not self._blocked()
        self.start_setup()

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
