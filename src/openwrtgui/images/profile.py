"""A profile: what an image holds, from a sysupgrade file or from a router's /rom (v0.5 plan, "Profile").

Keyed by board, revision and the image's sha256 ("rom" for a profile built from a router). Paths and texts
read from an image are data: they are kept verbatim and never run.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.overlay import mode_bits, parse_ls_ldn
from openwrtgui.images.apkdb import Package, is_custom, parse_apk_installed, parse_opkg_status
from openwrtgui.images.sysupgrade import ImageError, open_root, parse_layout
from openwrtgui.images.uci_file import parse_uci_file
from openwrtgui.images.usage import usage_text
from openwrtgui.probe.identity import parse_release
from openwrtgui.transport.base import Transport

PATH_DIRS = ("/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/libexec")
HASH_LIMIT = 2**20
READ_LIMIT = 8 * 2**20
_FOLDER = re.compile(r"[^A-Za-z0-9._,-]")


class ProfileKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    board: str
    revision: str
    sha256: str  # "rom" for a profile built from a router's /rom

    @property
    def folder(self) -> str:
        tail = "rom" if self.sha256 == "rom" else self.sha256[:12]
        return f"{_FOLDER.sub('_', self.revision)}-{tail}"

    @property
    def label(self) -> str:
        return f"{self.board} {self.revision}"


class ImageFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: Literal["file", "link", "other"]
    size: int
    mode: int
    target: str | None = None
    sha256: str | None = None


class CustomProgram(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    usage: str | None


class CustomPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    description: str
    programs: tuple[CustomProgram, ...]
    service: str | None


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    key: ProfileKey
    source: Literal["image", "rom"]
    image_name: str | None
    image_size: int | None
    firmware_len: int | None
    boards: tuple[str, ...]
    release: dict[str, str]
    packages: tuple[Package, ...]
    custom: tuple[CustomPackage, ...]
    files: tuple[ImageFile, ...]
    modules: tuple[str, ...]
    programs: tuple[str, ...]
    configs: dict[str, dict[str, str]]
    services: tuple[str, ...]
    uci_defaults: tuple[str, ...]
    built_at: datetime


def profile_paths(p: Profile) -> frozenset[str]:
    return frozenset(f.path for f in p.files)


def _children(paths: Iterator[str] | list[str], folder: str) -> list[str]:
    return sorted(posixpath.basename(p) for p in paths if posixpath.dirname(p) == folder)


def _custom(packages: tuple[Package, ...], programs: set[str], read: Any) -> tuple[CustomPackage, ...]:
    out: list[CustomPackage] = []
    for p in sorted((p for p in packages if is_custom(p)), key=lambda p: p.name):
        services = [posixpath.basename(f) for f in p.files if posixpath.dirname(f) == "/etc/init.d"]
        own = [f for f in p.files if f in programs]
        out.append(
            CustomPackage(
                name=p.name,
                version=p.version,
                description=p.description,
                programs=tuple(CustomProgram(path=f, usage=usage_text(read(f) or b"")) for f in own),
                service=services[0] if services else None,
            )
        )
    return tuple(out)


def _read(entries: dict[str, Any], path: str, limit: int = READ_LIMIT) -> bytes | None:
    entry = entries.get(path)
    if entry is None or not entry.is_file or entry.size > limit:
        return None
    data: bytes = entry.read_bytes()
    return data


def _entries(root: Any, name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        for entry in root.root.riter():
            try:
                path = entry.path
            except UnicodeDecodeError:
                continue
            if path != "/" and not entry.is_dir:
                out[path] = entry
    except Exception as exc:  # a damaged squashfs can fail anywhere inside the reader
        raise ImageError(f"{name}: the root file system could not be read ({exc})") from exc
    return out


def build_profile(data: bytes, name: str, built_at: datetime) -> Profile:
    layout = parse_layout(data, name)
    entries = _entries(open_root(data, layout), name)
    release_text = _read(entries, "/etc/openwrt_release")
    release = parse_release(release_text.decode("utf-8", "replace")) if release_text else {}
    if not release.get("DISTRIB_REVISION"):
        raise ImageError(f"{name} has no /etc/openwrt_release; it is not an OpenWrt root file system")
    apk = _read(entries, "/lib/apk/db/installed")
    opkg = _read(entries, "/usr/lib/opkg/status")
    if apk is not None:
        packages = parse_apk_installed(apk.decode("utf-8", "replace"))
    elif opkg is not None:
        lists = {
            posixpath.basename(p)[: -len(".list")]: (_read(entries, p) or b"").decode("utf-8", "replace")
            for p in entries
            if posixpath.dirname(p) == "/usr/lib/opkg/info" and p.endswith(".list")
        }
        packages = parse_opkg_status(opkg.decode("utf-8", "replace"), lists)
    else:
        raise ImageError(f"{name} has no package database (apk or opkg)")

    files: list[ImageFile] = []
    for path, entry in sorted(entries.items()):
        if entry.is_file:
            content = _read(entries, path, HASH_LIMIT)
            digest = hashlib.sha256(content).hexdigest() if content is not None else None
            files.append(
                ImageFile(path=path, kind="file", size=entry.size, mode=entry.mode & 0o7777, sha256=digest)
            )
        elif entry.is_symlink:
            files.append(
                ImageFile(
                    path=path, kind="link", size=entry.size, mode=entry.mode & 0o7777, target=entry.readlink()
                )
            )
        else:
            files.append(ImageFile(path=path, kind="other", size=entry.size, mode=entry.mode & 0o7777))
    paths = [f.path for f in files]
    programs = sorted(p for p in paths if posixpath.dirname(p) in PATH_DIRS)
    configs = {
        config: parse_uci_file(
            config, (_read(entries, f"/etc/config/{config}") or b"").decode("utf-8", "replace")
        )
        for config in _children(paths, "/etc/config")
    }
    metadata = layout.metadata
    boards = metadata.supported_devices if metadata else ()
    board = boards[0] if boards else release.get("DISTRIB_TARGET", "unknown").replace("/", "_")
    return Profile(
        key=ProfileKey(board=board, revision=release["DISTRIB_REVISION"], sha256=layout.sha256),
        source="image",
        image_name=name,
        image_size=len(data),
        firmware_len=layout.firmware_len,
        boards=boards,
        release=release,
        packages=packages,
        custom=_custom(packages, set(programs), lambda p: _read(entries, p, HASH_LIMIT)),
        files=tuple(files),
        modules=tuple(
            sorted(
                {posixpath.basename(p) for p in paths if p.startswith("/lib/modules/") and p.endswith(".ko")}
            )
        ),
        programs=tuple(programs),
        configs=configs,
        services=tuple(_children(paths, "/etc/init.d")),
        uci_defaults=tuple(_children(paths, "/etc/uci-defaults")),
        built_at=built_at,
    )


async def _text(t: Transport, command: str) -> str:
    result = await t.run(command)
    return result.stdout if result.ok else ""


async def build_rom_profile(t: Transport, board_name: str, built_at: datetime) -> Profile:
    """The same profile from a connected router's /rom (reads only): no file hashes, no firmware length."""
    release = parse_release(await _text(t, cmd.ROM_RELEASE))
    if not release.get("DISTRIB_REVISION"):
        raise ValueError("This router's /rom has no /etc/openwrt_release")
    apk = await t.run(cmd.ROM_APK_DB)
    if apk.ok:
        packages = parse_apk_installed(apk.stdout)
    else:
        packages = parse_opkg_status(await _text(t, cmd.ROM_OPKG_STATUS), {})
    listing, _unreadable = parse_ls_ldn(await _text(t, cmd.ROM_LS), "/rom")
    files = tuple(
        ImageFile(
            path=e.path,
            kind=e.kind if e.kind in ("file", "link") else "other",
            size=e.size,
            mode=mode_bits(e.mode),
            target=e.target,
        )
        for e in sorted(listing, key=lambda e: e.path)
    )
    paths = [f.path for f in files]
    programs = sorted(p for p in paths if posixpath.dirname(p) in PATH_DIRS)
    configs: dict[str, dict[str, str]] = {}
    for config in (await _text(t, cmd.ROM_CONFIG_LIST)).split():
        if cmd.CONFIG_NAME.fullmatch(config):
            configs[config] = parse_uci_file(config, await _text(t, cmd.rom_config(config)))
    usage: dict[str, bytes] = {}
    for p in packages:
        for f in p.files if is_custom(p) else ():
            if f in programs and cmd.SAFE_PATH.fullmatch(f):
                usage[f] = (await _text(t, cmd.rom_head(f))).encode()
    return Profile(
        key=ProfileKey(board=board_name, revision=release["DISTRIB_REVISION"], sha256="rom"),
        source="rom",
        image_name=None,
        image_size=None,
        firmware_len=None,
        boards=(board_name,),
        release=release,
        packages=packages,
        custom=_custom(packages, set(programs), usage.get),
        files=files,
        modules=tuple(
            sorted(
                {posixpath.basename(p) for p in paths if p.startswith("/lib/modules/") and p.endswith(".ko")}
            )
        ),
        programs=tuple(programs),
        configs=configs,
        services=tuple(sorted((await _text(t, cmd.ROM_SERVICES)).split())),
        uci_defaults=tuple(sorted((await _text(t, cmd.ROM_UCI_DEFAULTS)).split())),
        built_at=built_at,
    )
