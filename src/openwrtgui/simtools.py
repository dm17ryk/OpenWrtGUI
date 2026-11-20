"""The simulated router's tools (v1.2b): iperf3 and socat sessions as streams, and the `kill` that stops
them."""

from __future__ import annotations

import json
import re
import shlex

from openwrtgui.transport.base import CommandResult

SIM_PID = 4242
TCP_MBPS = 94.2
UDP_JITTER_MS = 0.05
SERVER_TEST_S = 5
REFUSED = (
    "unable to connect to server - server may have stopped running or use a different port, firewall issue, "
    "etc.: Connection refused"
)
LISTEN_PID = 4243
LISTEN_LINES = (
    "C4300 192.168.1.10 51515\n"
    "D4300=00000000  68 65 6c 6c 6f 0a                                 |hello.|\n"
    "D4300=00000006\n"
)
SEND_REFUSED = "2026/11/20 10:00:00 socat[77] E connect(5, AF=2 {host}:1, 16): Connection refused\n"
_SESSION = re.compile(r'echo "OWG-PID \$\$"; exec timeout -s KILL (\d+) (.+) 2>&1')
_KILL = re.compile(r"kill \d+")
_SEND = re.compile(
    r"(?:head -c \d+ /dev/zero|printf '%s\\n' '(?:[^']|'\\'')*') \| timeout -s KILL 30 socat -u - "
    r"(?:TCP:(?P<tcp>[^:]+):(?P<tport>\d+),connect-timeout=5|UDP-SENDTO:(?P<udp>[^:]+):(?P<uport>\d+)) 2>&1"
)


def _event(event: str, data: object) -> str:
    return json.dumps({"event": event, "data": data}) + "\n"


def _iperf3_lines(seconds: int, mbps: float, udp: bool) -> str:
    out = _event("start", {"version": "iperf 3.21", "test_start": {"duration": seconds}})
    for i in range(seconds):
        total: dict[str, object] = {"start": i, "end": i + 1, "seconds": 1, "bits_per_second": mbps * 1e6}
        if not udp:  # as on AP2: a UDP sender's seconds carry no jitter or loss, only the end's totals do
            total |= {"retransmits": 0}
        out += _event("interval", {"streams": [], "sum": total})
    if udp:
        end = {"sum": {"bits_per_second": mbps * 1e6, "jitter_ms": UDP_JITTER_MS, "lost_percent": 0}}
    else:
        end = {
            "sum_sent": {"bits_per_second": mbps * 1e6, "retransmits": 0},
            "sum_received": {"bits_per_second": (mbps - 0.2) * 1e6},
        }
    end["cpu_utilization_percent"] = {"host_total": 38.5}
    return out + _event("end", end)


class SimTools:
    """Answers only the commands it owns: a session's iperf3, and `kill <pid>`."""

    def answer(self, command: str) -> CommandResult | None:
        if _KILL.fullmatch(command):
            return CommandResult(command, "", "", 0)
        if m := _SEND.fullmatch(command):
            host, port = m.group("tcp") or m.group("udp"), m.group("tport") or m.group("uport")
            if port == "1":
                return CommandResult(command, SEND_REFUSED.format(host=host), "", 1)
            return CommandResult(command, "", "", 0)
        return None

    def stream(self, command: str) -> tuple[bytes, int] | None:
        """A session's whole output and its exit status; None for a command it does not own."""
        m = _SESSION.fullmatch(command)
        if m is None:
            return None
        args = shlex.split(m.group(2))
        if args[:1] == ["iperf3"]:
            text, status = self._iperf3(args[1:])
            return f"OWG-PID {SIM_PID}\n{text}".encode(), status
        if args[:1] == ["socat"]:  # Listen: one peer sends "hello\n"; the limit ends it
            return f"OWG-PID {LISTEN_PID}\n{LISTEN_LINES}".encode(), 137
        return None

    def _iperf3(self, args: list[str]) -> tuple[str, int]:
        def value(flag: str, default: str) -> str:
            return args[args.index(flag) + 1] if flag in args else default

        if "-s" in args:
            return _iperf3_lines(SERVER_TEST_S, TCP_MBPS, udp=False), 0
        if value("-p", "5201") == "1":
            return _event("start", {}) + _event("error", REFUSED), 1
        udp = "-u" in args
        mbps = float(value("-b", "1M").rstrip("M")) if udp else TCP_MBPS
        return _iperf3_lines(int(value("-t", "10")), mbps, udp), 0
