"""The modem's AT port (v0.6a plan D4) and the reads made on it (D2, D3, D10)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openwrtgui.lte import commands as c
from openwrtgui.lte.parse import parse_at, parse_cops, parse_mode_order, parse_modem_info
from openwrtgui.transport.base import Transport


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


async def read_modem_info(t: Transport, port: str | None) -> ModemInfo:
    if port is None:
        return ModemInfo()
    manufacturer, model, firmware = parse_modem_info(
        (await t.run(c.at(port, "AT+CGMI", "AT+CGMM", "AT+CGMR"))).stdout
    )
    cops = parse_at((await t.run(c.at(port, "AT+COPS?"))).stdout, "AT+COPS?")
    order = parse_at((await t.run(c.at(port, "AT+BMMODODR?"))).stdout, "AT+BMMODODR?")
    return ModemInfo(
        manufacturer=manufacturer,
        model=model,
        firmware=firmware,
        operator=parse_cops(cops.lines) if cops else None,
        mode_order=parse_mode_order(order.lines) if order else None,
        at_port=port,
    )
