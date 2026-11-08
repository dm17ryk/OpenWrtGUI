"""Busybox `ls -ldn` listings of /overlay/upper and /rom, kept as data whatever the names hold, and what the
overlay, the package database and the configs changed from the image (v0.5 plan, "Discovery rules")."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.images.apkdb import Package

if TYPE_CHECKING:
    from openwrtgui.images.profile import Profile

_LS = re.compile(r"(\S{10})\s+\d+\s+\d+\s+\d+\s+(?:(\d+)|(\d+),\s*(\d+))\s+\w{3}\s+\d+\s+[\d:]+\s(/.*)")

Kind = Literal["file", "link", "whiteout", "other"]


class OverlayEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: Kind
    size: int
    mode: str
    target: str | None = None


def mode_bits(mode: str) -> int:
    """`-rwxr-xr-x` → 0o755 (setuid, setgid and sticky shown as s, S, t, T)."""
    bits = 0
    for at, (char, value) in enumerate(zip(mode[1:10], (0o400, 0o200, 0o100) * 3, strict=False)):
        if char not in "-ST":
            bits |= value
        if char.lower() in "st" and at in (2, 5, 8):
            bits |= {2: 0o4000, 5: 0o2000, 8: 0o1000}[at]
    return bits


def parse_ls_ldn(text: str, root: str) -> tuple[tuple[OverlayEntry, ...], int]:
    """The entries under `root` (paths made relative to it) and how many lines could not be read."""
    entries: list[OverlayEntry] = []
    unreadable = 0
    prefix = root.rstrip("/") + "/"
    for line in text.splitlines():
        if not line.strip():
            continue
        found = _LS.fullmatch(line.strip(" "))
        if not found or not found.group(5).startswith(prefix):
            unreadable += 1
            continue
        mode, size, major, minor, path = found.groups()
        target: str | None = None
        if mode[0] == "l" and " -> " in path:
            path, target = path.split(" -> ", 1)
        if mode[0] == "-":
            kind: Kind = "file"
        elif mode[0] == "l":
            kind = "link"
        elif mode[0] == "c" and (major, minor) == ("0", "0"):
            kind = "whiteout"
        else:
            kind = "other"
        entries.append(
            OverlayEntry(
                path="/" + path[len(prefix) :], kind=kind, size=int(size or 0), mode=mode, target=target
            )
        )
    return tuple(entries), unreadable


class OverlayDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    added: tuple[OverlayEntry, ...]  # not in the image: added after flashing
    replaced: tuple[OverlayEntry, ...]  # a path the image has: changed from the image
    deleted: tuple[str, ...]  # an overlayfs whiteout on a path the image has
    unreadable: int


class PackageDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    added: tuple[Package, ...]
    removed: tuple[str, ...]
    changed: tuple[tuple[str, str, str], ...]  # name, image version, router version


class OptionChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    image: str | None
    router: str | None


class ConfigDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: str
    first_boot: bool  # the image has no default: the router made it at first boot
    changes: tuple[OptionChange, ...]


def diff_overlay(entries: Sequence[OverlayEntry], unreadable: int, profile: Profile) -> OverlayDiff:
    paths = {f.path for f in profile.files}
    ordered = sorted(entries, key=lambda e: e.path)
    return OverlayDiff(
        added=tuple(e for e in ordered if e.kind in ("file", "link") and e.path not in paths),
        replaced=tuple(e for e in ordered if e.kind in ("file", "link") and e.path in paths),
        deleted=tuple(e.path for e in ordered if e.kind == "whiteout" and e.path in paths),
        unreadable=unreadable,
    )


def diff_packages(live: Sequence[Package], profile: Profile) -> PackageDiff:
    image = {p.name: p.version for p in profile.packages}
    router = {p.name: p for p in live}
    return PackageDiff(
        added=tuple(sorted((p for p in live if p.name not in image), key=lambda p: p.name)),
        removed=tuple(sorted(name for name in image if name not in router)),
        changed=tuple(
            (name, image[name], p.version)
            for name, p in sorted(router.items())
            if name in image and image[name] != p.version
        ),
    )


def diff_configs(live: Mapping[str, Mapping[str, str]], profile: Profile) -> tuple[ConfigDiff, ...]:
    out: list[ConfigDiff] = []
    for config in sorted(set(live) | set(profile.configs)):
        if config not in profile.configs:
            out.append(ConfigDiff(config=config, first_boot=True, changes=()))
            continue
        image, router = profile.configs[config], live.get(config, {})
        changes = tuple(
            OptionChange(key=key, image=image.get(key), router=router.get(key))
            for key in sorted(set(image) | set(router))
            if image.get(key) != router.get(key)
        )
        if changes:
            out.append(ConfigDiff(config=config, first_boot=False, changes=changes))
    return tuple(out)
