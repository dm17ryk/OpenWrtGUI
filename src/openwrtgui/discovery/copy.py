"""Copy files added after flashing: read from one router, written to the same or another (v0.5 plan,
"Discovery rules › Copy files"). Paths are data: only SAFE_PATH ones are taken, never quoted into commands."""

from __future__ import annotations

import base64
import hashlib
import posixpath
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.discovery.commands import SAFE_PATH
from openwrtgui.discovery.overlay import OverlayEntry, mode_bits
from openwrtgui.transport.base import Transport, TransportError

MAX_FILE = 2**20
MAX_TOTAL = 4 * 2**20
_TARGET = re.compile(r"[A-Za-z0-9._/+@:=,-]{1,255}")
_OWN = ("/etc/dropbear/", "/etc/owg/")


class CopyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    paths: tuple[str, ...]
    target: str
    from_checklist: str | None = None  # a checklist's stamp: the files come from it, not from the router


class SavedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: Literal["file", "link"]
    mode: str
    size: int
    sha256: str | None
    target: str | None = None
    data: str | None = None  # base64


def _mb(size: int) -> int:
    return max(1, round(size / 2**20))


def _safe(path: str) -> bool:
    return bool(SAFE_PATH.fullmatch(path)) and "/../" not in f"{path}/" and "/./" not in f"{path}/"


def _secret(path: str) -> bool:
    """The router's password hashes and SSH host keys: never stored on this PC."""
    return path == "/etc/shadow" or path.startswith("/etc/dropbear/")


def check_copy_path(path: str, *, other_router: bool) -> None:
    if not _safe(path):
        raise ValueError(f"{path} has characters a copy does not take")
    if other_router and (path == "/etc/shadow" or path.startswith(_OWN)):
        raise ValueError(f"{path} is the router's own key or password; it is not copied")


async def _read(t: Transport, path: str) -> bytes:
    if not _safe(path):  # the path goes into a command: callers check it, this makes sure
        raise ValueError(f"{path} has characters a copy does not take")
    stream = getattr(t, "stream", None)
    if stream is None:
        raise TransportError("This connection cannot read files")
    reader = await stream(f"cat {path}")
    chunks: list[bytes] = []
    while chunk := await reader.read(65536):
        chunks.append(chunk)
    await reader.close()
    if reader.exit_status not in (0, None):
        raise ValueError(f"Could not read {path}: {reader.stderr.strip() or f'exit {reader.exit_status}'}")
    return b"".join(chunks)


async def read_files(t: Transport, entries: Sequence[OverlayEntry], *, strict: bool) -> tuple[SavedFile, ...]:
    """The entries' contents. strict (a copy): an unsafe name or a file over a limit is refused. Not strict
    (a checklist): those, and the router's password hashes and host keys, are listed without contents."""
    out: list[SavedFile] = []
    total = 0
    for e in entries:
        mode = f"{mode_bits(e.mode):04o}"
        if not _safe(e.path):
            if strict:
                raise ValueError(f"{e.path} has characters a copy does not take")
            out.append(SavedFile(path=e.path, kind="file", mode=mode, size=e.size, sha256=None))
            continue
        if e.kind == "link":
            if e.target is None or not _TARGET.fullmatch(e.target):
                if strict:
                    raise ValueError(f"{e.path} links to a target a copy does not take")
                continue
            out.append(
                SavedFile(path=e.path, kind="link", mode=mode, size=e.size, sha256=None, target=e.target)
            )
            continue
        if e.kind != "file":
            continue
        too_big = e.size > MAX_FILE or total + e.size > MAX_TOTAL
        if too_big and strict:
            if e.size > MAX_FILE:
                raise ValueError(f"{e.path} is {_mb(e.size)} MB; a copy takes files up to 1 MB")
            raise ValueError("A copy takes at most 4 MB in all")
        if too_big or (not strict and _secret(e.path)):
            out.append(SavedFile(path=e.path, kind="file", mode=mode, size=e.size, sha256=None))
            continue
        data = await _read(t, e.path)
        total += len(data)
        out.append(
            SavedFile(
                path=e.path,
                kind="file",
                mode=mode,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                data=base64.b64encode(data).decode(),
            )
        )
    return tuple(out)


def write_steps(f: SavedFile) -> list[tuple[str, bytes | None]]:
    """The commands that write one file (with the bytes for its stdin) and the read that proves it."""
    if f.kind == "link":
        return [(f"ln -sfn {f.target} {f.path}", None), (f"readlink {f.path}", None)]
    data = base64.b64decode(f.data or "")
    folder = posixpath.dirname(f.path) or "/"
    return [
        (f"mkdir -p {folder} && cat > {f.path}", data),
        (f"chmod {f.mode} {f.path}", None),
        (f"sha256sum {f.path}", None),
    ]
