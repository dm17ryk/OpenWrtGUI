"""The modem's AT port (v0.6a plan D4), the reads made on it (D2, D3, D10) and the console rules (D5)."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.lte import commands as c
from openwrtgui.lte.parse import AtAnswer, parse_at, parse_cops, parse_identity, parse_mode_order
from openwrtgui.transport.base import Transport

IDENTITY = ("AT+CGMI", "AT+CGMM", "AT+CGMR")  # one exec each: the BM806C drops the third of a burst (AP2)
IDENTITY_READS = (*IDENTITY, "AT+BMMODODR?")  # what ModemIdentity holds, read once per connection (v1.0c D2)
_QUERY = re.compile(r"AT(I|\+CSQ|\+CGM[IMR]|[+%][A-Z0-9]+(\?|=\?))?", re.IGNORECASE)


def is_query(text: str) -> bool:
    """D5: the forms that read and cannot change the modem; they run any time, even during a harness run."""
    return _QUERY.fullmatch(text.strip()) is not None


class AtResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    command: str
    lines: tuple[str, ...]
    status: Literal["OK", "ERROR", "no answer"]
    error: str | None


class ModemInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    operator: str | None = None
    mode_order: int | None = None
    at_port: str | None = None


async def find_at_port(t: Transport) -> str | None:
    """`AT` to each /dev/ttyUSB* in name order (as the image's dwr921-at-probe does); the first `OK`."""
    listed = (await t.run(c.TTY_LIST)).stdout.split()
    for port in sorted(p for p in listed if c.AT_PORT.fullmatch(p)):
        answer = parse_at((await t.run(c.at(port, "AT"))).stdout, "AT")
        if answer is not None and answer.status == "OK":
            return port
    return None


class ModemIdentity(BaseModel):
    """What does not change while the modem stays enumerated: kept per connection (v1.0c D2)."""

    model_config = ConfigDict(frozen=True)

    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    mode_order: int | None = None

    @property
    def silent(self) -> bool:
        """Nothing answered: the port gave no identity at all."""
        return self.model_dump(exclude_none=True) == {}


async def read_identity(t: Transport, port: str) -> ModemIdentity:
    manufacturer, model, firmware = [
        parse_identity((await t.run(c.at(port, command))).stdout, command) for command in IDENTITY
    ]
    order = parse_at((await t.run(c.at(port, "AT+BMMODODR?"))).stdout, "AT+BMMODODR?")
    return ModemIdentity(
        manufacturer=manufacturer,
        model=model,
        firmware=firmware,
        mode_order=parse_mode_order(order.lines) if order else None,
    )


async def complete_identity(t: Transport, port: str, known: ModemIdentity | None) -> ModemIdentity:
    """The kept identity with any part the modem did not answer asked again, alone (the final review: a modem
    still coming up may skip one answer). Nothing kept: all four are asked."""
    if known is None:
        return await read_identity(t, port)
    fields: dict[str, str | int | None] = {}
    for name, command in zip(("manufacturer", "model", "firmware"), IDENTITY, strict=True):
        if getattr(known, name) is None:
            fields[name] = parse_identity((await t.run(c.at(port, command))).stdout, command)
    if known.mode_order is None:
        order = parse_at((await t.run(c.at(port, "AT+BMMODODR?"))).stdout, "AT+BMMODODR?")
        fields["mode_order"] = parse_mode_order(order.lines) if order else None
    return known.model_copy(update=fields) if fields else known


async def operator_answer(t: Transport, port: str) -> AtAnswer | None:
    """AT+COPS?, asked on every read; None: the port gave no answer at all."""
    return parse_at((await t.run(c.at(port, "AT+COPS?"))).stdout, "AT+COPS?")


async def read_operator(t: Transport, port: str) -> str | None:
    cops = await operator_answer(t, port)
    return parse_cops(cops.lines) if cops else None


def modem_info(identity: ModemIdentity | None, operator: str | None, port: str | None) -> ModemInfo:
    known = identity or ModemIdentity()
    return ModemInfo(
        manufacturer=known.manufacturer,
        model=known.model,
        firmware=known.firmware,
        operator=operator,
        mode_order=known.mode_order,
        at_port=port,
    )


async def read_modem_info(t: Transport, port: str | None) -> ModemInfo:
    """Everything at once, read afresh (the recorded-AP2 contract reads it this way)."""
    if port is None:
        return ModemInfo()
    identity = await read_identity(t, port)
    return modem_info(identity, await read_operator(t, port), port)
