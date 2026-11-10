"""Backup (v0.6b plan D9): `sysupgrade -b -` read as bytes into <data>/backups/<router>/, readable by this
user only. The archive holds the router's password hash, its SSH host keys, the app's key line and the Wi-Fi
keys: it never goes into a log, a fixture or the audit log (one line there names the file)."""

from __future__ import annotations

import asyncio
import contextlib
import re
from datetime import datetime
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict

from openwrtgui.store.keys import restrict_to_user
from openwrtgui.system import commands as s
from openwrtgui.transport.base import Streamer, Transport

GZIP = b"\x1f\x8b"
CHUNK = 65536


IMPORTED = "-imported"


class BackupFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    size: int
    created_at: datetime
    imported: bool = False  # a file brought in from the PC (v0.6c), not read from the router


def backup_dir(root: Path, router_id: str) -> Path:
    return root / "backups" / router_id


def backup_name(router_id: str, now: datetime, *, imported: bool = False) -> str:
    return f"{router_id}-{now:%Y%m%d-%H%M%S}{IMPORTED if imported else ''}.tar.gz"


def listing(folder: Path, router_id: str) -> list[BackupFile]:
    """The router's saved archives, newest first: names this app gave them (any id length)."""
    if not folder.is_dir():
        return []
    name = re.compile(rf"{re.escape(router_id)}-\d{{8}}-\d{{6}}(?:{IMPORTED})?\.tar\.gz")
    files = [p for p in folder.iterdir() if p.is_file() and name.fullmatch(p.name)]
    out = [
        BackupFile(
            name=p.name,
            size=p.stat().st_size,
            created_at=datetime.fromtimestamp(p.stat().st_mtime).astimezone(),
            imported=p.name.endswith(f"{IMPORTED}.tar.gz"),
        )
        for p in files
    ]
    return sorted(out, key=lambda b: b.name, reverse=True)


def check_kept(text: str) -> str:
    """/etc/sysupgrade.conf as the router keeps it (D10): each line blank, a # comment or an absolute path."""
    from openwrtgui.system.commands import KEPT_PATH, MAX_FILE

    if len(text.encode()) > MAX_FILE:
        raise ValueError("The list is at most 8 KiB")
    lines = text.replace("\r\n", "\n").split("\n")
    for n, line in enumerate(lines, start=1):
        item = line.strip()
        if item and not item.startswith("#") and not KEPT_PATH.fullmatch(item):
            raise ValueError(f"line {n}: {item!r} is not an absolute path (or a # comment)")
    return "\n".join(lines).rstrip("\n") + "\n"


async def save_upload(path: Path, data: bytes) -> None:
    """An imported archive into the data folder, user-only before a byte lands (no half file stays)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(restrict_to_user, path.parent)
    part = path.with_name(path.name + ".part")
    try:
        with part.open("xb") as sink:
            await asyncio.to_thread(restrict_to_user, part)
            sink.write(data)
    except BaseException:
        with contextlib.suppress(OSError):
            part.unlink()
        raise
    part.replace(path)


async def save_archive(t: Transport, path: Path) -> tuple[int, int | None, str]:
    """Stream the archive into `path` (made user-only before a byte lands): (bytes, exit status, problem).
    The file is removed again when the router gave no archive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict_to_user(path.parent)
    part = path.with_name(path.name + ".part")
    total = 0
    problem = ""
    try:
        with part.open("xb") as sink:
            restrict_to_user(part)
            stream = await cast(Streamer, t).stream(s.BACKUP)
            try:
                while chunk := await stream.read(CHUNK):
                    if total == 0 and not chunk.startswith(GZIP):
                        problem = "not a gzip archive"
                        break
                    sink.write(chunk)
                    total += len(chunk)
            finally:
                await stream.close()
    except BaseException:  # a lost connection, a full disk: no half archive (secrets) stays behind
        with contextlib.suppress(OSError):
            part.unlink()
        raise
    status = stream.exit_status
    if not problem and status not in (0, None):
        problem = stream.stderr.strip() or f"exit {status}"
    if not problem and total == 0:
        problem = "an empty archive"
    if problem:
        with contextlib.suppress(OSError):
            part.unlink()
        return total, status, problem
    part.replace(path)
    return total, status, ""
