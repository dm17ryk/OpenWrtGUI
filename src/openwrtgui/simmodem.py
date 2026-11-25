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
    "AT+BMMODODR=?": ("+BMMODODR: (2,3,17)",),
    "AT+CUSD=2": (),
}
_MICROCOM = re.compile(
    r"printf '%s\\r' (.+) \| timeout -s KILL (?:10 microcom -t 2000|35 microcom -t 30000)"
    r" -s 115200 (/dev/ttyUSB[0-9])"
)
_CUSD = re.compile(r'AT\+CUSD=1,"([^"]*)",15', re.IGNORECASE)
MESSAGE_TIME = "2026-01-01T12:00:00+00:00"
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
        # tests: the SIM's PIN state ("disabled", "not_verified", "verified", "blocked"), tries, accepted PIN
        self.pin1 = "disabled"
        self.pin1_tries = 3
        self.puk_tries = 10
        self.pin_code = "0000"
        self.messages: dict[str, dict[int, dict[str, object]]] = {
            "sim": {i: {"sender": f"+155501{i + 1:02d}", "text": f"Test message {i + 1}"} for i in range(3)},
            "me": {},
        }
        self.capacity = {"sim": 20, "me": 23}
        self.sent: list[tuple[str, str]] = []
        self.ussd_replies: dict[str, tuple[int, str, int]] = {
            "*100#": (0, "Balance 12.34", 15),
            "*111#": (1, "1 Balance 2 Packages", 15),
            "*200#": (0, "05E905DC05D505DD", 72),
        }
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
        sim = self._sim_or_messages(command)
        if sim is not None:
            return sim
        return _fail("Invalid argument\n")

    def _sim_state(self, *, unlock_key: str) -> CommandResult:
        card = "ready" if self.pin1 in ("disabled", "verified") else "pin_required"
        state: dict[str, object] = {}
        if unlock_key == "pin1_unlock_tries":  # --uim-get-sim-state; --get-pin-status has no card keys
            state.update(card_slot=1, card_application_state=card)
        state.update(pin1_status=self.pin1, pin1_verify_tries=self.pin1_tries)
        state[unlock_key] = self.puk_tries
        state.update(pin2_status="not_verified", pin2_verify_tries=3)
        state["pin2_" + unlock_key.removeprefix("pin1_")] = 10
        return _ok(json.dumps(state, separators=(",", ":")) + "\n")

    def _verify_pin(self, pin: str) -> CommandResult:
        if self.pin1 != "not_verified":
            return _fail("Request failed\n")
        if pin == self.pin_code:
            self.pin1 = "verified"
            return _ok()
        self.pin1_tries = max(0, self.pin1_tries - 1)
        if self.pin1_tries == 0:
            self.pin1 = "blocked"
        return _fail("Request failed\n")  # never echoes the PIN

    def _sim_or_messages(self, command: str) -> CommandResult | None:
        """The SIM and SMS options: `uqmi -s -d DEV -t MS <option> [args]`."""
        try:
            words = shlex.split(command)
        except ValueError:
            return None
        option, args = (words[6], words[7:]) if len(words) > 6 else ("", [])
        if option == "--uim-get-sim-state":
            return self._sim_state(unlock_key="pin1_unlock_tries")
        if option == "--get-pin-status":
            return self._sim_state(unlock_key="pin1_unblock_tries")
        if option == "--verify-pin1" and len(args) == 1:
            return self._verify_pin(args[0])
        if option == "--send-message" and len(args) == 3 and args[1] == "--send-message-target":
            self.sent.append((args[2], args[0]))
            return _ok()
        if option not in ("--list-messages", "--get-message", "--delete-message"):
            return None
        by_id = option != "--list-messages"
        if len(args) != (3 if by_id else 2) or args[-2] != "--storage" or args[-1] not in self.messages:
            return _fail("Invalid argument\n")
        store = self.messages[args[-1]]
        if not by_id:
            return _ok(json.dumps(sorted(store), separators=(",", ":")) + "\n")
        message = store.get(int(args[0])) if args[0].isdigit() else None
        if message is None:
            return _fail("Request failed\n")
        if option == "--delete-message":
            del store[int(args[0])]
            return _ok()
        body = {"smsc": "+15550100", "timestamp": MESSAGE_TIME, **message}
        return _ok(json.dumps(body, separators=(",", ":")) + "\n")

    def _cpms(self) -> str:
        me, sim = self.messages["me"], self.messages["sim"]
        cap = self.capacity
        return f'+CPMS: "ME",{len(me)},{cap["me"]},"ME",{len(me)},{cap["me"]},"SM",{len(sim)},{cap["sim"]}'

    def _at_lines(self, command: str) -> tuple[str, ...] | None:
        upper = command.upper()
        if upper == "AT+CPIN?":
            return ("+CPIN: READY" if self.pin1 in ("disabled", "verified") else "+CPIN: SIM PIN",)
        if upper == "AT+CPMS?":
            return (self._cpms(),)
        if _CUSD.fullmatch(command) is not None:
            return ()  # the reply comes after the OK (_ussd_line)
        return AT_ANSWERS.get(upper)

    def _ussd_line(self, command: str) -> str | None:
        """The network's +CUSD answer to a USSD request; none for a code the network does not know."""
        m = _CUSD.fullmatch(command)
        reply = self.ussd_replies.get(m.group(1)) if m is not None else None
        return None if reply is None else f'+CUSD: {reply[0]},"{reply[1]}",{reply[2]}'

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
            lines = self._at_lines(command)
            if lines is None and re.fullmatch(r"AT\+[A-Z]+=.*", command, re.IGNORECASE):
                lines = ()  # a setting the simulator accepts
            if lines is None:
                out.append("ERROR\r\n")
                continue
            out.extend(f"{line}\r\n\r\n" for line in lines)
            out.append("OK\r\n")
            if (ussd := self._ussd_line(command)) is not None:
                out.append(f"\r\n{ussd}\r\n")
        return _ok("".join(out))
