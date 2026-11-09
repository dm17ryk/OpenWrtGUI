"""busybox crond's crontab (v0.6b plan D7): each line a comment, blank, a variable, or five time fields and a
command. A field crond cannot read makes the task silently never run, so it is refused here with its line."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
# name, lowest, highest, names (index 0 = lowest), message
_FIELDS: tuple[tuple[str, int, int, tuple[str, ...], str], ...] = (
    ("minute", 0, 59, (), "minute is 0-59"),
    ("hour", 0, 23, (), "hour is 0-23"),
    ("day", 1, 31, (), "day is 1-31"),
    ("month", 1, 12, _MONTHS, "month is 1-12 or jan-dec"),
    ("weekday", 0, 7, _DAYS, "weekday is 0-7 or sun-sat"),
)
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
SHAPE = "a task is five time fields and a command"


@dataclass(frozen=True)
class CronComment:
    """A comment, a blank line or a variable: kept as written."""

    text: str


@dataclass(frozen=True)
class CronLine:
    minute: str
    hour: str
    day: str
    month: str
    weekday: str
    command: str


CronEntry = CronComment | CronLine


def _value(text: str, low: int, high: int, names: tuple[str, ...]) -> int | None:
    if text.isdigit():
        value = int(text)
        return value if low <= value <= high else None
    if text.lower() in names:
        return names.index(text.lower()) + low
    return None


def _field_ok(text: str, low: int, high: int, names: tuple[str, ...]) -> bool:
    for part in text.split(","):
        span, _, step = part.partition("/")
        if step and not (step.isdigit() and 0 < int(step) <= high):
            return False
        if span == "*":
            continue
        start, dash, end = span.partition("-")
        first = _value(start, low, high, names)
        last = _value(end, low, high, names) if dash else first
        if first is None or last is None or first > last or (step and not dash):
            return False
    return True


def _entry(line: str, number: int) -> CronEntry:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or _VARIABLE.fullmatch(stripped):
        return CronComment(line)
    parts = stripped.split(None, 5)
    if len(parts) < 6:
        raise ValueError(f"line {number}: {SHAPE}")
    for text, (_name, low, high, names, message) in zip(parts[:5], _FIELDS, strict=True):
        if not _field_ok(text, low, high, names):
            raise ValueError(f"line {number}: {message}")
    return CronLine(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5])


def parse_crontab(text: str) -> list[CronEntry]:
    return [_entry(line, number) for number, line in enumerate(text.splitlines(), start=1)]


def check_crontab(text: str) -> str:
    """The text as it will be written (one newline at the end); a bad line raises with its number."""
    parse_crontab(text)
    lines = text.splitlines()
    return "".join(f"{line}\n" for line in lines)
