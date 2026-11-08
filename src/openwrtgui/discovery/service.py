"""Discovery per router: the state read, the firmware check, the dashboard summary, and (later tasks)
copies, tools and services."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, MutableMapping
from datetime import datetime

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.firmware import FirmwareCheck, image_prefix_sha256, parse_proc_mtd
from openwrtgui.discovery.state import DiscoveryState, DiscoverySummary, no_match_note, read_discovery
from openwrtgui.fw import commands as fwc
from openwrtgui.fw.nft import parse_ruleset_json
from openwrtgui.fw.owners import nft_objects, tc_hooks
from openwrtgui.fw.tc import parse_qdiscs
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.images.profile import Profile
from openwrtgui.images.store import ProfileStore
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import SettingsStore
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

log = logging.getLogger(__name__)
SCREEN = "Discovery"
FIRMWARE_TIMEOUT_S = 120.0


class DiscoveryService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        settings: SettingsStore,
        descriptions: MutableMapping[str, SelfDescription],
        profiles: ProfileStore,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._settings = settings
        self._descriptions = descriptions
        self._profiles = profiles
        self._clock = clock
        self.summaries: dict[str, DiscoverySummary] = {}

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _described(self, rec: RouterRecord, t: Transport) -> SelfDescription:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        return desc

    async def _context(
        self, router_id: str
    ) -> tuple[RouterRecord, Transport, SelfDescription, Profile | None]:
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        desc = await self._described(rec, t)
        return rec, t, desc, self._profiles.match(desc.identity.board_name, desc.identity.revision)

    async def state(self, router_id: str) -> DiscoveryState:
        rec, t, desc, profile = await self._context(router_id)
        return await read_discovery(
            t, router_id=rec.id, identity=desc.identity, profile=profile, now=self._clock()
        )

    async def check_firmware(self, router_id: str) -> FirmwareCheck:
        rec, t, desc, profile = await self._context(router_id)
        if profile is None:
            raise ValueError(no_match_note(desc.identity.board_name, desc.identity.revision))
        length = profile.firmware_len
        if profile.source != "image" or length is None:
            raise ValueError("Import the image file to check the firmware")
        state = self._guard.state()
        if state.live:
            run = state.reasons[0].text if state.reasons else "a harness run"
            megabytes = max(1, round(length / 2**20))
            raise ValueError(f"The firmware check reads {megabytes} MB of flash; not while {run} runs")
        image = self._profiles.image_bytes(profile.key)
        index = parse_proc_mtd((await t.run(cmd.PROC_MTD)).stdout).get("firmware")
        if index is None:
            raise ValueError(f"{rec.name} has no mtd partition named firmware")
        started = time.monotonic()
        result = await t.run(cmd.firmware_hash(index, length), timeout=FIRMWARE_TIMEOUT_S)
        read_s = round(time.monotonic() - started, 1)
        expected = image_prefix_sha256(image, length)
        words = result.stdout.split()
        if not result.ok or not words:
            reason = (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"
            return FirmwareCheck(
                matches=None,
                detail=f"Could not read the firmware partition: {reason}",
                image_sha256=expected,
                router_sha256=None,
                read_s=read_s,
            )
        name = profile.image_name or profile.key.label
        matches = words[0] == expected
        detail = (
            f"The firmware matches {name}"
            if matches
            else f"The firmware differs from {name} (flashed from another build, or changed since)"
        )
        return FirmwareCheck(
            matches=matches, detail=detail, image_sha256=expected, router_sha256=words[0], read_s=read_s
        )

    async def _owners(self, t: Transport) -> tuple[str, ...]:
        ruleset = parse_ruleset_json((await t.run(fwc.NFT_JSON)).stdout)
        tags = [
            f"{o.chain or o.table} · {o.writer or o.owner}"
            for o in nft_objects(ruleset, self._settings.load().known_tables)
            if o.owner != "fw4"
        ]
        tags += [
            f"{h.dev} {h.kind} · {h.owner}"
            for h in tc_hooks(parse_qdiscs((await t.run(fwc.TC_QDISCS)).stdout), frozenset())
        ]
        return tuple(tags)

    async def summary(self, router_id: str) -> DiscoverySummary:
        rec, t, desc, profile = await self._context(router_id)
        state = await read_discovery(
            t, router_id=rec.id, identity=desc.identity, profile=profile, now=self._clock()
        )
        summary = DiscoverySummary(
            profile=profile.key.label if profile is not None else None,
            files_added=len(state.overlay.added),
            packages_added=len(state.packages.added),
            configs_changed=sum(1 for c in state.configs if not c.first_boot),
            owners=await self._owners(t),
            reflash_pending=False,
        )
        self.summaries[rec.id] = summary
        return summary

    async def refresh_summary(self, rec: RouterRecord) -> None:
        """The poller's hook: once per connect (the cache is cleared on import, delete and flash)."""
        if rec.id in self.summaries:
            return
        try:
            await self.summary(rec.id)
        except (TransportError, ValueError) as exc:
            log.debug("discovery summary of %s failed: %s", rec.id, exc)
