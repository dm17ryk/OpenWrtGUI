"""SMS messages as uqmi lists them, the modem's storage use, and the text rule for sending."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openwrtgui.lte.commands import Storage

GSM_RULE = "An SMS is 1 to 160 characters of the GSM basic set (letters, digits, common punctuation)"
MAX_TEXT = 160
# The identity subset of the 3GPP TS 23.038 basic table: only the characters whose GSM-7 code equals their
# ASCII code. uqmi packs the argument's bytes into 7 bits without a translation table, so @ $ _ (GSM codes
# 0x00, 0x02, 0x11) and the non-ASCII letters would arrive as other characters.
GSM_7BIT_BASIC: frozenset[str] = frozenset(
    "\n !\"#%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_CPMS_USE = re.compile(r'"(ME|SM)"\s*,\s*(\d+)\s*,\s*(\d+)')
_STORAGE_OF: dict[str, Storage] = {"ME": "me", "SM": "sim"}


@dataclass(frozen=True)
class SmsMessage:
    id: int
    storage: Storage
    sender: str | None
    time: str | None
    text: str | None
    part: str | None


def _object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def parse_ids(text: str) -> tuple[int, ...] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if not isinstance(value, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in value):
        return None
    return tuple(value)


def parse_message(text: str, message_id: int, storage: Storage) -> SmsMessage | None:
    data = _object(text)
    if data is None:
        return None
    part = None
    if isinstance(data.get("concat_part"), int) and isinstance(data.get("concat_parts"), int):
        part = f"{data['concat_part']} of {data['concat_parts']}"
    return SmsMessage(
        id=message_id,
        storage=storage,
        sender=_str(data.get("sender")),
        time=_str(data.get("timestamp")),
        text=_str(data.get("text")),
        part=part,
    )


def parse_cpms(lines: Sequence[str]) -> dict[Storage, tuple[int, int]]:
    """AT+CPMS? answers three (storage, used, capacity) groups; the first of each storage counts."""
    use: dict[Storage, tuple[int, int]] = {}
    for line in lines:
        if not line.startswith("+CPMS:"):
            continue
        for name, used, capacity in _CPMS_USE.findall(line):
            use.setdefault(_STORAGE_OF[name], (int(used), int(capacity)))
    return use


def check_text(text: str) -> str:
    if not 1 <= len(text) <= MAX_TEXT or not set(text) <= GSM_7BIT_BASIC:
        raise ValueError(GSM_RULE)
    return text
