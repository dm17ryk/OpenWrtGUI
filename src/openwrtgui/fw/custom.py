"""Custom rule files (`/etc/nftables.d/*.nft`, which fw4 loads into its table): an edit is checked by
rendering fw4's ruleset with it (`fw4 print`) through `nft -c` before fw4 reloads, under a router-side
timer that puts the old file back."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from openwrtgui.fw.tables import heredoc
from openwrtgui.net.apply import ROLLBACK_ID

CUSTOM_DIR = "/etc/nftables.d"
MAX_BYTES = 64 * 1024
_NAME = re.compile(r"[A-Za-z0-9_-]{1,60}")
BAK = f"/tmp/owg/rb-{ROLLBACK_ID}.bak"
CHECK = f"/tmp/owg/rb-{ROLLBACK_ID}.check"


@dataclass(frozen=True)
class CustomFile:
    path: str
    name: str
    content: str
    from_image: bool
    lines: int
    comments_only: bool


@dataclass(frozen=True)
class CustomRequest:
    name: str  # without .nft
    content: str | None  # None deletes the file


def parse_custom(listing: str, rom: str) -> list[CustomFile]:
    """The `=== <path>` listing of every file, and `ls /rom/etc/nftables.d` (the image's own files)."""
    image = set(rom.split())
    files: list[CustomFile] = []
    path: str | None = None
    body: list[str] = []

    def close() -> None:
        if path is None:
            return
        content = "".join(body)
        name = path.rsplit("/", 1)[-1].removesuffix(".nft")
        meaningful = [x for x in content.splitlines() if x.strip()]
        files.append(
            CustomFile(
                path,
                name,
                content,
                path.rsplit("/", 1)[-1] in image,
                content.count("\n"),
                all(x.lstrip().startswith("#") for x in meaningful),
            )
        )

    for line in listing.splitlines(keepends=True):
        if line.startswith("=== /"):
            close()
            path, body = line[4:].strip(), []
        else:
            body.append(line)
    close()
    return files


def custom_change(
    req: CustomRequest, files: Sequence[CustomFile]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(backup, restore, commands) for one file."""
    if not _NAME.fullmatch(req.name):
        raise ValueError("A rules file name is 1 to 60 letters, digits, - or _")
    path = f"{CUSTOM_DIR}/{req.name}.nft"
    exists = any(f.path == path for f in files)
    if req.content is None and not exists:
        raise ValueError(f"There is no rules file {req.name}")
    if req.content is not None and len(req.content.encode()) > MAX_BYTES:
        raise ValueError("A rules file is at most 64 KiB")
    backup = (f"cp {path} {BAK}",) if exists else ()
    restore = (f"cp {BAK} {path}" if exists else f"rm -f {path}", "fw4 reload")
    write = heredoc(f"cat > {path}", req.content.rstrip("\n")) if req.content is not None else f"rm -f {path}"
    return backup, restore, (write, f"fw4 print > {CHECK} && nft -c -f {CHECK}", "fw4 reload")
