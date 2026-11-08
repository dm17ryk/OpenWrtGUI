"""Package databases: apk's `/lib/apk/db/installed` and opkg's `/usr/lib/opkg/status`.

A package with neither a license nor a URL is one of the bench's own (decision D8): on the bench image exactly
the three `dwr921-*` packages are, while every upstream package carries one or both.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

_DEPEND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


class Package(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    description: str = ""
    origin: str = ""
    license: str = ""
    url: str = ""
    depends: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


def is_custom(p: Package) -> bool:
    return not p.license.strip() and not p.url.strip()


def _apk_block(block: str) -> Package | None:
    fields: dict[str, str] = {}
    files: list[str] = []
    folder = ""
    for line in block.splitlines():
        if len(line) < 2 or line[1] != ":":
            continue
        key, value = line[0], line[2:]
        if key == "F":
            folder = value.strip("/")
        elif key == "R":
            files.append(f"/{folder}/{value}" if folder else f"/{value}")
        else:
            fields.setdefault(key, value)
    if not fields.get("P"):
        return None
    return Package(
        name=fields["P"],
        version=fields.get("V", ""),
        description=fields.get("T", ""),
        origin=fields.get("o", ""),
        license=fields.get("L", ""),
        url=fields.get("U", ""),
        depends=tuple(fields.get("D", "").split()),
        files=tuple(files),
    )


def parse_apk_installed(text: str) -> tuple[Package, ...]:
    blocks = re.split(r"\n\s*\n", text)
    return tuple(p for p in (_apk_block(b) for b in blocks) if p is not None)


def _opkg_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    key = ""
    for line in block.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] += " " + line.strip()
            continue
        key, sep, value = line.partition(":")
        if not sep:
            key = ""
            continue
        fields[key] = value.strip()
    return fields


def parse_opkg_status(text: str, lists: Mapping[str, str]) -> tuple[Package, ...]:
    out: list[Package] = []
    for block in re.split(r"\n\s*\n", text):
        fields = _opkg_fields(block)
        name = fields.get("Package", "")
        if not name:
            continue
        depends = [
            m.group(0) for part in fields.get("Depends", "").split(",") if (m := _DEPEND.match(part.strip()))
        ]
        out.append(
            Package(
                name=name,
                version=fields.get("Version", ""),
                description=fields.get("Description", ""),
                license=fields.get("License", ""),
                url=fields.get("URL", ""),
                depends=tuple(depends),
                files=tuple(line.strip() for line in lists.get(name, "").splitlines() if line.strip()),
            )
        )
    return tuple(out)
