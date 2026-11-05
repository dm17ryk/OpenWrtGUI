"""Audit log: one JSON line per command the app sends on someone's behalf, secrets masked."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

HIDDEN = "<hidden>"
SECRET_OPTIONS = (
    "key",
    "key1",
    "key2",
    "key3",
    "key4",  # WEP
    "password",
    "pincode",
    "psk",
    "sae_password",
    "multi_ap_backhaul_key",  # a Wi-Fi passphrase
    "auth_secret",
    "acct_secret",
    "dae_secret",
    "auth_server_shared_secret",
    "acct_server_shared_secret",
    "priv_key_pwd",
    "priv_key2_pwd",
    "private_key_passwd",
    "private_key2_passwd",
    "wps_pin",
    "ap_pin",
    "r0kh",
    "r1kh",  # FT key holders carry their keys
    "private_key",
    "preshared_key",  # WireGuard
)
_SECRET_OPTIONS = "|".join(SECRET_OPTIONS)
# uci set <cfg>.<section>.<option>=value, with the value quoted '…' (a ' inside written as '\''),
# "…" or bare.
_UCI_SECRET = re.compile(
    rf"(\.(?:{_SECRET_OPTIONS})=)('(?:[^']*'\\'')*[^']*'|\"(?:[^\"\\]|\\.)*\"|[^\s;&|'\"]+)"
)
# The same options in JSON (ubus call uci set / ubus call network …).
_JSON_SECRET = re.compile(rf"(\"(?:{_SECRET_OPTIONS})\"\s*:\s*)\"(?:[^\"\\]|\\.)*\"")


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
    return _JSON_SECRET.sub(rf'\1"{HIDDEN}"', command)


class AuditLog:
    def __init__(self, audit_dir: Path) -> None:
        self.dir = audit_dir
        self.dir.mkdir(parents=True, exist_ok=True)

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
