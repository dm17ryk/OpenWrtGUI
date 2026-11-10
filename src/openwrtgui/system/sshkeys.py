"""System › Access › SSH keys (v0.6c plan D5): `/etc/dropbear/authorized_keys` read as LuCI's SSH-Keys
page reads it. A key keeps its options and comment; any other line is kept as written, so a write never
loses it."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

import asyncssh
from pydantic import BaseModel, ConfigDict

MAX_KEY_LINE = 16 * 1024
KEY_TYPES = (
    "ssh-dss",
    "ssh-rsa",
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ecdsa-sha2-nistp256@openssh.com",
    "sk-ssh-ed25519@openssh.com",
)
_TYPES = (
    r"ssh-dss|ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp[0-9]+"
    r"|sk-ecdsa-sha2-nistp256@openssh\.com|sk-ssh-ed25519@openssh\.com"
)
# LuCI's own pattern (sshkeys.js): leading options, the type, the base64 blob, the comment
_LINE = re.compile(
    r'^((?:(?:^|,)[^ =,]+(?:=(?:[^ ",]+|"(?:[^"\\]|\\.)*"))?)+ +)?(' + _TYPES + r") +([^ ]+)( +.*)?$"
)

KeyLabel = Literal["app", "harness", "other"]


class KeyLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    text: str
    type: str | None  # None: not a key line, kept as written
    comment: str
    options: str | None
    fingerprint: str | None


def _key(index: int, text: str) -> KeyLine | None:
    m = _LINE.match(text)
    if not m:
        return None
    options, key_type, blob, comment = m.groups()
    try:
        fingerprint = asyncssh.import_public_key(f"{key_type} {blob}").get_fingerprint("sha256")
    except (asyncssh.KeyImportError, ValueError):
        return None
    return KeyLine(
        index=index,
        text=text,
        type=key_type,
        comment=(comment or "").strip(),
        options=options.strip() if options else None,
        fingerprint=fingerprint,
    )


def parse_authorized_keys(text: str) -> list[KeyLine]:
    out: list[KeyLine] = []
    for index, line in enumerate(text.splitlines()):
        out.append(
            _key(index, line)
            or KeyLine(index=index, text=line, type=None, comment="", options=None, fingerprint=None)
        )
    return out


def check_key_line(line: str) -> KeyLine:
    """A key to add: one line, a type LuCI knows, a blob that decodes."""
    text = line.strip()
    if not text:
        raise ValueError("Paste a public key")
    if "\n" in text or "\r" in text:
        raise ValueError("Paste one key per line")
    if len(text.encode()) > MAX_KEY_LINE:
        raise ValueError("A key line is at most 16 KiB")
    m = _LINE.match(text)
    if not m:
        raise ValueError(f"This is not an SSH public key line ({', '.join(KEY_TYPES)})")
    found = _key(0, text)
    if found is None:
        raise ValueError("The key does not decode")
    return found


def render_authorized_keys(lines: Sequence[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def label(
    fingerprint: str | None, app: Collection[str], known: Mapping[str, str]
) -> tuple[KeyLabel, str | None]:
    """App: a key this app logs in to the router with; harness: a key named in Settings (its owner)."""
    if fingerprint is not None and fingerprint in app:
        return "app", None
    if fingerprint is not None and fingerprint in known:
        return "harness", known[fingerprint]
    return "other", None
