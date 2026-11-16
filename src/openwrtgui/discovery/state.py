"""What Discovery shows for one router: how it differs from its matched image, its custom packages and
programs, and the capability map (v0.5 plan, "Discovery rules", "Tools rules").

Configs the image has no default for (network, wireless, …) are listed by name only and never read: their
values (Wi-Fi keys among them) have no image default to compare with.
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.capabilities import CapabilityRow, capability_map
from openwrtgui.discovery.overlay import (
    ConfigDiff,
    OverlayDiff,
    OverlayEntry,
    PackageDiff,
    diff_configs,
    diff_overlay,
    diff_packages,
    parse_ls_ldn,
)
from openwrtgui.discovery.services import SERVICE_NAME, ServiceRow, read_service
from openwrtgui.guard.secrets import shown
from openwrtgui.images.apkdb import Package, is_custom, parse_apk_installed, parse_opkg_status
from openwrtgui.images.profile import PATH_DIRS, Profile, ProfileKey
from openwrtgui.images.usage import usage_text
from openwrtgui.probe.identity import Identity
from openwrtgui.transport.base import Transport
from openwrtgui.uci import parse_uci_show

BUILTIN_CARDS = {"dwr921-portctl": "ports"}  # a custom package a built-in screen already drives


class ProgramRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    usage: str | None
    source: Literal["custom", "overlay"]
    has_card: bool


class CustomRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    package: str
    version: str
    description: str
    source: Literal["image", "added after flashing"]
    programs: tuple[ProgramRow, ...]
    card: str | None  # a screen ("ports") or "promoted"
    service: str | None


class DiscoveryState(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    read_at: datetime
    board: str
    revision: str
    profile: ProfileKey | None
    match_note: str | None
    has_overlay: bool
    overlay: OverlayDiff
    packages: PackageDiff
    configs: tuple[ConfigDiff, ...]
    kept_on_flash: tuple[str, ...]
    kept_known: bool = True  # False: `sysupgrade -l` failed, so what a flash keeps is unknown
    custom: tuple[CustomRow, ...]
    programs: tuple[ProgramRow, ...]
    services: tuple[ServiceRow, ...] = ()
    capabilities: tuple[CapabilityRow, ...]


class DiscoverySummary(BaseModel):
    """What the dashboard shows per router: the matched image, counts, and owner tags (spec 7.1)."""

    model_config = ConfigDict(frozen=True)

    profile: str | None
    files_added: int
    packages_added: int
    configs_changed: int
    owners: tuple[str, ...]
    reflash_pending: bool


def no_match_note(board: str, revision: str) -> str:
    return (
        f"No imported image for {board} {revision}. Import its sysupgrade image (Settings › Images), "
        "or build a profile from this router's /rom."
    )


def hide_secrets(diffs: Sequence[ConfigDiff]) -> tuple[ConfigDiff, ...]:
    """Compared on the real values, shown with secret ones hidden (v1.0b1 D3): a changed key stays listed."""
    return tuple(
        d.model_copy(
            update={
                "changes": tuple(
                    c.model_copy(update={"image": shown(c.key, c.image), "router": shown(c.key, c.router)})
                    for c in d.changes
                )
            }
        )
        for d in diffs
    )


async def _usage(t: Transport, path: str) -> str | None:
    if not cmd.SAFE_PATH.fullmatch(path):
        return None
    result = await t.run(cmd.head(path))
    return usage_text(result.stdout.encode()) if result.ok else None


async def _live_packages(t: Transport) -> tuple[Package, ...]:
    apk = await t.run(cmd.APK_DB)
    if apk.ok:
        return parse_apk_installed(apk.stdout)
    opkg = await t.run(cmd.OPKG_STATUS)
    return parse_opkg_status(opkg.stdout, {}) if opkg.ok else ()


def _added_packages(profile: Profile, live: Sequence[Package]) -> list[Package]:
    """Custom packages installed after flashing: live, custom, and not in the image."""
    image = {p.name for p in profile.packages}
    return [p for p in live if p.name not in image and is_custom(p)]


def _program_files(files: Sequence[str]) -> list[str]:
    return [f for f in files if posixpath.dirname(f) in PATH_DIRS]


def _overlay_programs(overlay: OverlayDiff, owned: set[str]) -> list[OverlayEntry]:
    """Files added in a program folder that no live package owns."""
    return [e for e in overlay.added if posixpath.dirname(e.path) in PATH_DIRS and e.path not in owned]


async def listed_programs(t: Transport, profile: Profile | None) -> frozenset[str]:
    """The custom programs the Discovery page lists, read in two commands (v1.0c Task 5, #17): the overlay
    listing and the live packages, without the configs, usages and services the page also reads."""
    if profile is None:
        return frozenset()  # without a matched image the page lists no programs
    entries, unreadable = parse_ls_ldn((await t.run(cmd.OVERLAY_LS)).stdout, "/overlay/upper")
    live = await _live_packages(t)
    owned = {f for p in live for f in p.files}
    from_image = {p.path for c in profile.custom for p in c.programs}
    added = {f for p in _added_packages(profile, live) for f in _program_files(p.files)}
    overlay = {e.path for e in _overlay_programs(diff_overlay(entries, unreadable, profile), owned)}
    return frozenset(from_image | added | overlay)


async def _custom_rows(
    t: Transport, profile: Profile, live: Sequence[Package], card_paths: frozenset[str]
) -> tuple[CustomRow, ...]:
    rows: list[CustomRow] = []
    for c in profile.custom:
        programs = tuple(
            ProgramRow(path=p.path, usage=p.usage, source="custom", has_card=p.path in card_paths)
            for p in c.programs
        )
        rows.append(_row(c.name, c.version, c.description, "image", programs, c.service))
    for p in _added_packages(profile, live):
        added: list[ProgramRow] = []
        for f in _program_files(p.files):
            added.append(
                ProgramRow(path=f, usage=await _usage(t, f), source="custom", has_card=f in card_paths)
            )
        services = [posixpath.basename(f) for f in p.files if posixpath.dirname(f) == "/etc/init.d"]
        rows.append(
            _row(
                p.name,
                p.version,
                p.description,
                "added after flashing",
                tuple(added),
                next(iter(services), None),
            )
        )
    return tuple(rows)


def _row(
    name: str,
    version: str,
    description: str,
    source: Literal["image", "added after flashing"],
    programs: tuple[ProgramRow, ...],
    service: str | None,
) -> CustomRow:
    card = BUILTIN_CARDS.get(name) or ("promoted" if any(p.has_card for p in programs) else None)
    return CustomRow(
        package=name,
        version=version,
        description=description,
        source=source,
        programs=programs,
        card=card,
        service=service,
    )


async def read_discovery(
    t: Transport,
    *,
    router_id: str,
    identity: Identity,
    profile: Profile | None,
    card_paths: frozenset[str] = frozenset(),
    now: datetime,
) -> DiscoveryState:
    listing = await t.run(cmd.OVERLAY_LS)
    entries, unreadable = parse_ls_ldn(listing.stdout, "/overlay/upper")
    has_overlay = listing.ok or bool(entries)
    empty = DiscoveryState(
        router_id=router_id,
        read_at=now,
        board=identity.board_name,
        revision=identity.revision,
        profile=None,
        match_note=no_match_note(identity.board_name, identity.revision),
        has_overlay=has_overlay,
        overlay=OverlayDiff(added=(), replaced=(), deleted=(), unreadable=unreadable),
        packages=PackageDiff(added=(), removed=(), changed=()),
        configs=(),
        kept_on_flash=(),
        custom=(),
        programs=(),
        capabilities=(),
    )
    if profile is None:
        return empty
    overlay = diff_overlay(entries, unreadable, profile)
    live = await _live_packages(t)
    names = {n for n in (await t.run(cmd.CONFIG_LIST)).stdout.split() if cmd.CONFIG_NAME.fullmatch(n)}
    configs: dict[str, dict[str, str]] = {name: {} for name in names}
    for name in sorted(set(profile.configs) & names):
        result = await t.run(cmd.uci_show(name))
        configs[name] = parse_uci_show(result.stdout) if result.ok else {}
    keep_list = await t.run(cmd.SYSUPGRADE_LIST)
    kept = set(keep_list.stdout.split()) if keep_list.ok else set()
    owned = {f for p in live for f in p.files}
    custom = await _custom_rows(t, profile, live, card_paths)
    programs: list[ProgramRow] = []
    for e in _overlay_programs(overlay, owned):
        usage = await _usage(t, e.path) if e.kind == "file" else None
        programs.append(ProgramRow(path=e.path, usage=usage, source="overlay", has_card=e.path in card_paths))
    return empty.model_copy(
        update={
            "profile": profile.key,
            "match_note": None,
            "overlay": overlay,
            "packages": diff_packages(live, profile),
            "configs": hide_secrets(diff_configs(configs, profile)),
            "kept_on_flash": tuple(e.path for e in (*overlay.added, *overlay.replaced) if e.path in kept),
            "kept_known": keep_list.ok,
            "custom": custom,
            "programs": tuple(programs),
            "services": await _services(t, custom, overlay, owned),
            "capabilities": capability_map(profile, overlay),
        }
    )


async def _services(
    t: Transport, custom: Sequence[CustomRow], overlay: OverlayDiff, owned: set[str]
) -> tuple[ServiceRow, ...]:
    """Init scripts of custom packages, then those the overlay added that no package owns."""
    found: list[tuple[str, Literal["custom", "overlay"], str | None]] = [
        (row.service, "custom", row.package) for row in custom if row.service
    ]
    found += [
        (posixpath.basename(e.path), "overlay", None)
        for e in overlay.added
        if posixpath.dirname(e.path) == "/etc/init.d" and e.kind == "file" and e.path not in owned
    ]
    rows: list[ServiceRow] = []
    for name, source, package in found:
        if not SERVICE_NAME.fullmatch(name) or any(r.name == name for r in rows):
            continue
        running, enabled = await read_service(t, name)
        rows.append(ServiceRow(name=name, source=source, package=package, running=running, enabled=enabled))
    return tuple(rows)
