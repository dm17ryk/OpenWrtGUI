"""AP2's recorded LTE reads (tests/fixtures/ap2/lte.json, 2026-11-09) against the LTE parsers, the AT port
search and the whole state read. The recording itself found three things the simulator did not show: QMI's
operator name is not valid UTF-8, ttyUSB3 never takes bytes (only ttyUSB0-1 are probed), and the BM806C drops
the third of a burst of AT commands."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from openwrtgui.lte import commands as c
from openwrtgui.lte.at import find_at_port, read_modem_info
from openwrtgui.lte.parse import parse_at, parse_cops, parse_mode_order, parse_serving, parse_signal
from openwrtgui.lte.state import measures, read_lte
from openwrtgui.transport.base import CommandResult

RECORDING: dict[str, dict[str, object]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "lte.json").read_text(encoding="utf-8")
)
LTE_LIST = "ls /dev/ttyUSB* /dev/cdc-wdm*"
DEVICE = "/dev/cdc-wdm0"
AT_PORT = "/dev/ttyUSB1"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _out(command: str) -> str:
    entry = RECORDING[command]
    assert entry["exit"] == 0, (command, entry.get("stderr"))
    return str(entry["stdout"])


class Recorded:
    """Replays the recording; `ls /dev/ttyUSB*` is the tty part of the recorded listing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        if command == c.TTY_LIST:
            ttys = [p for p in _out(LTE_LIST).split() if c.AT_PORT.fullmatch(p)]
            return CommandResult(command, "".join(f"{p}\n" for p in ttys), "", 0)
        entry = RECORDING.get(command)
        if entry is None:
            return CommandResult(command, "", "not recorded", 127)
        return CommandResult(
            command, str(entry["stdout"]), str(entry.get("stderr", "")), int(str(entry["exit"]))
        )


def test_serving_system_parses() -> None:
    s = parse_serving(_out(c.SERVING(DEVICE)))
    assert s is not None
    assert (s.registration, s.radio, s.roaming, s.mcc, s.mnc) == ("registered", "lte", False, 425, 1)
    assert s.qmi_name is not None and "�" in s.qmi_name  # O3: garbled bytes read as U+FFFD, not a drop


def test_signal_parses() -> None:
    signal = parse_signal(_out(c.SIGNAL(DEVICE)))
    assert signal is not None
    assert (signal.type, signal.rssi, signal.rsrq, signal.rsrp) == ("lte", -60, -15, -95)
    assert signal.snr is not None and round(signal.snr, 1) == 8.2  # uqmi prints 8.2000000000000011
    labels = {metric: m.label for metric, m in measures(signal).items() if m is not None}
    assert labels == {"rssi": "excellent", "rsrq": "good", "rsrp": "fair", "snr": "fair"}  # -15 is a boundary


async def test_at_port_is_found() -> None:
    t = Recorded()
    assert await find_at_port(t) == AT_PORT  # type: ignore[arg-type]
    assert not any("ttyUSB2" in call or "ttyUSB3" in call for call in t.calls)


async def test_modem_info_parses() -> None:
    info = await read_modem_info(Recorded(), AT_PORT)  # type: ignore[arg-type]
    assert (info.manufacturer, info.model, info.firmware) == ("BroadMobi", "BM806C", "M1.2.0_E1.0.3_A1.1.8")


def test_operator_from_at() -> None:
    answer = parse_at(_out(c.at(AT_PORT, "AT+COPS?")), "AT+COPS?")
    assert answer is not None and parse_cops(answer.lines) == "Partner"


def test_mode_order_reads() -> None:
    answer = parse_at(_out(c.at(AT_PORT, "AT+BMMODODR?")), "AT+BMMODODR?")
    assert answer is not None and parse_mode_order(answer.lines) == 17


async def test_lte_status_reads() -> None:
    s = await read_lte(Recorded(), router_id="ap2", qmi=("lte", DEVICE), at_port=AT_PORT, now=NOW)  # type: ignore[arg-type]
    assert s.available and (s.up, s.pending, s.uptime_s) == (True, False, 2222552)
    assert s.ipv4 is None  # lte_4 is pending on AP2: no DHCP lease yet, so no address to show
    assert (s.rx_bytes, s.tx_bytes) == (12173, 257532310)
    assert (s.registration, s.radio, s.operator, s.operator_source) == ("registered", "lte", "Partner", "at")
    assert s.opmode == "online" and s.modem.at_port == AT_PORT and s.missing == ()
