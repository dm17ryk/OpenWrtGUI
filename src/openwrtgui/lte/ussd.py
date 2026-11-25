"""The modem's +CUSD answer to a USSD code, as a typed reply."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

_UCS2 = 2
_EIGHT_BIT = 1
_STATUS_OF_M: dict[int, Literal["reply", "more", "ended"]] = {
    0: "reply",
    1: "more",
    2: "ended",
    3: "ended",  # P4: another local client responded
}


@dataclass(frozen=True)
class UssdReply:
    status: Literal["reply", "more", "ended", "no reply", "error"]
    text: str | None
    dcs: int | None
    closed: bool


def parse_cusd(lines: Sequence[str]) -> tuple[int, str | None, int | None] | None:
    """+CUSD: <m>[,"<text>",<dcs>]. The text may hold commas and quotes, so only the first and the
    last comma split the reply."""
    for line in lines:
        if not line.startswith("+CUSD:"):
            continue
        rest = line[len("+CUSD:") :].strip()
        head, comma, tail = rest.partition(",")
        if not head.strip().isdigit():
            return None
        m = int(head)
        if not comma:
            return m, None, None
        body, _, last = tail.rpartition(",")
        dcs = None
        if body and last.strip().isdigit():
            dcs = int(last)
        else:
            body = tail
        body = body.strip()
        if body.startswith('"'):
            body = body[1:]
        if body.endswith('"'):
            body = body[:-1]
        return m, body, dcs
    return None


def _alphabet(dcs: int) -> int | None:
    """The 2-bit alphabet field of the DCS groups that carry one (1 = 8-bit, 2 = UCS-2)."""
    if dcs == 0x11:
        return _UCS2
    if (dcs & 0xC0) == 0x40 or (dcs & 0xF0) == 0x90:
        return (dcs >> 2) & 3
    return None


def decode(text: str, dcs: int | None) -> str:
    """UCS-2 arrives as hex and is decoded; 8-bit data and anything undecodable stay as given."""
    if dcs is None or _alphabet(dcs) != _UCS2:
        return text
    try:
        return bytes.fromhex(text).decode("utf-16-be")
    except ValueError:
        return text


def reply_of(parsed: tuple[int, str | None, int | None] | None) -> UssdReply:
    if parsed is None:
        return UssdReply(status="no reply", text=None, dcs=None, closed=False)
    m, text, dcs = parsed
    return UssdReply(
        status=_STATUS_OF_M.get(m, "error"),
        text=None if text is None else decode(text, dcs),
        dcs=dcs,
        closed=False,
    )
