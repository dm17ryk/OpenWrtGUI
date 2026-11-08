"""What uqmi, the modem's AT port and netifd answer, as typed values. Anything that is not the expected
shape is "no answer" (None): the screen shows the parts it could read."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

_COPS = re.compile(r'\+COPS:\s*\d+\s*,\s*\d+\s*,\s*"([^"]*)"')
_MODE_ORDER = re.compile(r"\+BMMODODR:\s*(\d+)")
_CGM_PREFIX = re.compile(r"^\+CGM[IMR]:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ServingSystem:
    registration: str | None
    radio: str | None
    roaming: bool | None
    mcc: int | None
    mnc: int | None
    qmi_name: str | None


@dataclass(frozen=True)
class Signal:
    type: str | None
    rssi: float | None
    rsrp: float | None
    rsrq: float | None
    snr: float | None
    ecio: float | None
    rscp: float | None


@dataclass(frozen=True)
class AtAnswer:
    lines: tuple[str, ...]
    status: Literal["OK", "ERROR"]
    error: str | None


def _object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value: object) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse_serving(text: str) -> ServingSystem | None:
    data = _object(text)
    if data is None:
        return None
    radios = data.get("radio_interface")
    radio = radios[0] if isinstance(radios, list) and radios and isinstance(radios[0], str) else None
    roaming = data.get("roaming")
    return ServingSystem(
        registration=_str(data.get("registration")),
        radio=radio,
        roaming=roaming if isinstance(roaming, bool) else None,
        mcc=_int(data.get("plmn_mcc")),
        mnc=_int(data.get("plmn_mnc")),
        qmi_name=_str(data.get("plmn_description")),
    )


def parse_signal(text: str) -> Signal | None:
    data = _object(text)
    if data is None:
        return None
    return Signal(
        type=_str(data.get("type")),
        rssi=_num(data.get("rssi")),
        rsrp=_num(data.get("rsrp")),
        rsrq=_num(data.get("rsrq")),
        snr=_num(data.get("snr")),
        ecio=_num(data.get("ecio")),
        rscp=_num(data.get("rscp")),
    )


def parse_opmode(text: str) -> str | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]


def _is_status(line: str) -> bool:
    return line in ("OK", "ERROR") or line.startswith(("+CME ERROR:", "+CMS ERROR:"))


def parse_at(text: str, command: str) -> AtAnswer | None:
    """The answer to one AT command, with or without the modem's echo; None without a final status line."""
    lines = [ln for ln in _lines(text) if ln.upper() != command.strip().upper()]
    final = next((i for i in range(len(lines) - 1, -1, -1) if _is_status(lines[i])), None)
    if final is None:
        return None
    body = tuple(ln for ln in lines[:final] if not _is_status(ln))
    if lines[final] == "OK":
        return AtAnswer(lines=body, status="OK", error=None)
    return AtAnswer(lines=body, status="ERROR", error=lines[final])


def parse_cops(lines: Sequence[str]) -> str | None:
    for line in lines:
        if m := _COPS.search(line):
            return m.group(1)
    return None


def parse_mode_order(lines: Sequence[str]) -> int | None:
    for line in lines:
        if m := _MODE_ORDER.search(line):
            return int(m.group(1))
    return None


def parse_modem_info(text: str) -> tuple[str | None, str | None, str | None]:
    """The answers to AT+CGMI, AT+CGMM, AT+CGMR sent in one exec: manufacturer, model, firmware."""
    answers: list[str | None] = []
    first: str | None = None
    for line in _lines(text):
        if line.upper().startswith("AT"):  # the echo of the next command
            continue
        if _is_status(line):
            answers.append(first if line == "OK" else None)
            first = None
        elif first is None:
            first = _CGM_PREFIX.sub("", line) or None
    padded = [*answers[:3], None, None, None]
    return padded[0], padded[1], padded[2]
