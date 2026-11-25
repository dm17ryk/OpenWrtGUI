"""Audit log: one JSON line per command the app sends on someone's behalf, secrets masked."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

# re-exported: the terminal, the forms and the masks below use them from here
from openwrtgui.guard.secrets import HIDDEN as HIDDEN
from openwrtgui.guard.secrets import SECRET_OPTIONS as SECRET_OPTIONS

log = logging.getLogger(__name__)

_SECRET_OPTIONS = "|".join(SECRET_OPTIONS)
# uci set <cfg>.<section>.<option>=value, with the value quoted '…' (a ' inside written as '\''),
# "…" or bare.
_UCI_SECRET = re.compile(
    rf"(\.(?:{_SECRET_OPTIONS})=)('(?:[^']*'\\'')*[^']*'|\"(?:[^\"\\]|\\.)*\"|[^\s;&|'\"]+)"
)
# The same options in JSON (ubus call uci set / ubus call network …).
_JSON_SECRET = re.compile(rf"(\"(?:{_SECRET_OPTIONS})\"\s*:\s*)\"(?:[^\"\\]|\\.)*\"")
# SIM PINs sent as AT commands (3GPP 27.007 +CPIN, +CLCK, +CPWD): everything after `=` up to the end of the
# shell-quoted argument (a ' inside written as '\''), so neither the PIN nor its pieces stay visible.
# A modem ignores spaces, so `AT + CPIN = 1234` carries the PIN too, and APN passwords travel in +CGAUTH,
# Quectel's +QICSGP and Qualcomm's $QCPDPP. A `=?` query carries nothing and stays readable (final review).
AT_MASKED_COMMANDS = r"[+$]\s*(?:CPIN|CLCK|CPWD|CGAUTH|QICSGP|QCPDPP)\s*=(?!\s*\?)"
_AT_SECRET = re.compile(rf"({AT_MASKED_COMMANDS})((?:'\\''|[^'\r\n])*)", re.IGNORECASE)
# a PIN or PUK given to uqmi as an option value (v1.3b): `--verify-pin1 1234`
_UQMI_PIN = re.compile(r"(--(?:uim-)?verify-pin[12]|--pin|--new-pin|--puk)\s+\S+")
# an SMS text given to uqmi (v1.3b E6), shell-quoted '…' with a ' inside written as '\'': hidden by its
# position, whole, so neither a ' inside nor a text as short as one digit can leave it in clear or shred the
# number after it (final review I1, security M1/L3)
_UQMI_SMS_TEXT = re.compile(r"(--send-message )('(?:[^']*'\\'')*[^']*'|\S+)")


def _hide_value(match: re.Match[str]) -> str:
    value = match.group(2)
    quote = value[0] if value[0] in "'\"" else ""
    return f"{match.group(1)}{quote}{HIDDEN}{quote}"


Source = Literal["user", "wizard", "terminal", "app"]


@dataclass(frozen=True)
class AuditEntry:
    ts: datetime
    router: str | None
    screen: str
    command: str
    exit_status: int | None
    verify: str | None
    source: Source


def mask(command: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        if secret:
            command = command.replace(secret, HIDDEN)
    command = _UCI_SECRET.sub(_hide_value, command)
    command = _AT_SECRET.sub(rf"\1{HIDDEN}", command)
    command = _UQMI_PIN.sub(rf"\1 {HIDDEN}", command)
    command = _UQMI_SMS_TEXT.sub(rf"\1'{HIDDEN}'", command)
    return _JSON_SECRET.sub(rf'\1"{HIDDEN}"', command)


class AuditLog:
    def __init__(self, audit_dir: Path) -> None:
        self.dir = audit_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        # called with the router id after each line about a router: every change the app makes is audited, so
        # a listener hears about all of them (v1.0b2 D2: the LuCI menu facts go stale)
        self.on_record: list[Callable[[str], None]] = []

    def record(
        self,
        *,
        router: str | None,
        screen: str,
        command: str,
        exit_status: int | None,
        verify: str | None = None,
        source: Source,
        secrets: Sequence[str] = (),
    ) -> AuditEntry:
        entry = AuditEntry(
            ts=datetime.now().astimezone(),
            router=router,
            screen=screen,
            command=mask(command, secrets),
            exit_status=exit_status,
            verify=verify,
            source=source,
        )
        with (self.dir / f"{entry.ts.date().isoformat()}.jsonl").open("a", encoding="utf-8") as f:
            f.write(_line(entry))
        if router is not None:
            for listener in self.on_record:
                listener(router)
        return entry

    def _read(self, day: Path) -> list[AuditEntry]:
        out: list[AuditEntry] = []
        for raw in day.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(raw)
                data["ts"] = datetime.fromisoformat(data["ts"])
                # Masked again: an older version wrote its entries knowing fewer secret options.
                data["command"] = mask(str(data["command"]), ())
                out.append(AuditEntry(**data))
            except (ValueError, KeyError, TypeError):
                log.warning("skipped an unreadable audit line in %s", day.name)
        return out

    def _entries(self) -> list[AuditEntry]:
        return [e for day in sorted(self.dir.glob("*.jsonl")) for e in self._read(day)]

    def query(
        self,
        *,
        router: str | None = None,
        text: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[AuditEntry]:
        found = [
            e
            for e in reversed(self._entries())
            if (router is None or e.router == router)
            and (text is None or text.lower() in e.command.lower() or text.lower() in e.screen.lower())
            and (since is None or e.ts >= (since if since.tzinfo else since.astimezone()))
        ]
        return found[:limit]

    def prune(self, retention_days: int, today: date) -> int:
        if retention_days == 0:
            return 0
        cutoff = today - timedelta(days=retention_days)
        removed = 0
        for day in self.dir.glob("*.jsonl"):
            try:
                file_day = date.fromisoformat(day.stem)
            except ValueError:
                continue
            if file_day < cutoff:
                day.unlink()
                removed += 1
        return removed

    def export_zip(self, dest: Path) -> Path:
        """The entries as the viewer shows them: masked again, unreadable lines left out."""
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for day in sorted(self.dir.glob("*.jsonl")):
                z.writestr(day.name, "".join(_line(e) for e in self._read(day)))
        return dest


def _line(entry: AuditEntry) -> str:
    return json.dumps({**asdict(entry), "ts": entry.ts.isoformat()}, ensure_ascii=False) + "\n"
