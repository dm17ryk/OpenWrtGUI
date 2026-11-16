"""read_lte (v1.0c D3): the uqmi and netifd reads run alongside the AT exchange; a lost link ends both."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

import pytest

from openwrtgui.lte import commands as c
from openwrtgui.lte.at import ModemIdentity
from openwrtgui.lte.state import read_lte
from openwrtgui.transport.base import CommandResult, TransportError

DEV = "/dev/cdc-wdm0"
PORT = "/dev/ttyUSB2"
NOW = datetime(2026, 11, 16, 9, 0)
KNOWN = ModemIdentity(manufacturer="Maker", model="M1", firmware="1.0", mode_order=17)
SIGNAL_JSON = '{"type": "lte", "rssi": -60, "rsrq": -15, "rsrp": -95, "snr": 8.2}'
COPS_OK = 'AT+COPS?\r\r\n+COPS: 0,0,"TestNet",7\r\n\r\nOK\r\n'

Answer = Callable[[], Awaitable[str]]


class Scripted:
    """Answers the commands it is given (an answer may wait or raise); anything else exits 0, empty."""

    def __init__(self, answers: dict[str, Answer]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        answer = self.answers.get(command)
        return CommandResult(command, await answer() if answer is not None else "", "", 0)


def wait_then(event: asyncio.Event, out: str) -> Answer:
    async def answer() -> str:
        await event.wait()
        return out

    return answer


def start_then(event: asyncio.Event, out: str) -> Answer:
    async def answer() -> str:
        event.set()
        return out

    return answer


def raises(exc: Exception) -> Answer:
    async def answer() -> str:
        raise exc

    return answer


async def test_the_modem_reads_overlap_the_at_exchange() -> None:
    cops_started = asyncio.Event()
    t = Scripted(
        {
            # the uqmi read waits for the AT exchange to start: only an overlap gets past it
            c.SIGNAL(DEV): wait_then(cops_started, SIGNAL_JSON),
            c.at(PORT, "AT+COPS?"): start_then(cops_started, COPS_OK),
        }
    )
    state, identity = await asyncio.wait_for(
        read_lte(t, router_id="ap1", qmi=("lte", DEV), at_port=PORT, now=NOW, identity=KNOWN),  # type: ignore[arg-type]
        2.0,
    )
    assert state.operator == "TestNet" and state.rssi is not None
    assert identity == KNOWN and state.modem.model == "M1" and state.modem.mode_order == 17
    assert not any("AT+CGM" in call for call in t.calls)  # a known identity is not asked again


async def test_a_dropped_connection_ends_both_halves_and_keeps_no_identity() -> None:
    t = Scripted({c.at(PORT, "AT+CGMI"): raises(TransportError("lost"))})  # the first identity read
    with pytest.raises(TransportError):
        await read_lte(t, router_id="ap1", qmi=("lte", DEV), at_port=PORT, now=NOW, identity=None)  # type: ignore[arg-type]
    assert c.SIGNAL(DEV) in t.calls  # the other half ran to its end, not left running
