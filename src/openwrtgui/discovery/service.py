"""Discovery per router: the state read, the firmware check, the dashboard summary, and (later tasks)
copies, tools and services."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, MutableMapping
from datetime import datetime

from openwrtgui.discovery import commands as cmd
from openwrtgui.discovery.checklist import ChecklistStore, ReflashChecklist
from openwrtgui.discovery.copy import CopyRequest, SavedFile, check_copy_path, read_files, write_steps
from openwrtgui.discovery.firmware import FirmwareCheck, image_prefix_sha256, parse_proc_mtd
from openwrtgui.discovery.overlay import parse_ls_ldn
from openwrtgui.discovery.state import DiscoveryState, DiscoverySummary, no_match_note, read_discovery
from openwrtgui.fw import commands as fwc
from openwrtgui.fw.nft import parse_ruleset_json
from openwrtgui.fw.owners import nft_objects, tc_hooks
from openwrtgui.fw.tc import parse_qdiscs
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited, run_audited_upload, upload_line
from openwrtgui.images.profile import Profile
from openwrtgui.images.store import ProfileStore
from openwrtgui.net.apply import NetApplyResult, NetCheck, NetPlan, net_plan
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import SettingsStore
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)
SCREEN = "Discovery"
FIRMWARE_TIMEOUT_S = 120.0


def _proof(f: SavedFile, out: str) -> NetCheck:
    """A copied file proven by its sha256 (a link by readlink) read back on the target."""
    name = f"file {f.path}"
    got = (out.split() or [""])[0].strip()
    want = f.target if f.kind == "link" else f.sha256
    if got == want:
        return NetCheck(name, True, "sha256 matches" if f.kind == "file" else f"links to {want}")
    return NetCheck(name, False, f"read back {got[:12] or 'nothing'}, expected {(want or '')[:12]}")


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
        checklists: ChecklistStore,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._settings = settings
        self._descriptions = descriptions
        self._profiles = profiles
        self.checklists = checklists
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

    # ---------------------------------------------------------------- copies and checklists
    async def _copy_files(
        self, source_id: str, req: CopyRequest
    ) -> tuple[RouterRecord, tuple[SavedFile, ...]]:
        source = self._record(source_id)
        target = self._record(req.target)
        if not req.paths:
            raise ValueError("Pick the files to copy")
        for path in req.paths:
            check_copy_path(path, other_router=target.id != source.id)
        if req.from_checklist is not None:
            checklist = self.checklists.get(source.id, req.from_checklist)
            if checklist is None:
                raise ValueError(f"No reflash checklist {req.from_checklist} for {source.name}")
            saved = {f.path: f for f in checklist.lost}
            for path in req.paths:
                f = saved.get(path)
                if f is None or (f.kind == "file" and f.data is None):
                    raise ValueError(f"{path} is not in that checklist with its contents")
            return target, tuple(saved[p] for p in req.paths)
        t = await self._pool.get(source)
        entries, _ = parse_ls_ldn((await t.run(cmd.OVERLAY_LS)).stdout, "/overlay/upper")
        by_path = {e.path: e for e in entries if e.kind in ("file", "link")}
        for path in req.paths:
            if path not in by_path:
                raise ValueError(
                    f"{path} is not in {source.name}'s overlay "
                    "(only files added or changed after flashing are copied)"
                )
        return target, await read_files(t, [by_path[p] for p in req.paths], strict=True)

    @staticmethod
    def _copy_plan(source_id: str, target: RouterRecord, files: tuple[SavedFile, ...]) -> NetPlan:
        lines = [
            upload_line(command, f"{source_id}:{f.path}", data) if data is not None else command
            for f in files
            for command, data in write_steps(f)
        ]
        return net_plan(router_id=target.id, screen=SCREEN, config=None, ops=[], current={}, commands=lines)

    async def plan_copy(self, source_id: str, req: CopyRequest) -> NetPlan:
        target, files = await self._copy_files(source_id, req)
        return self._copy_plan(source_id, target, files)

    async def apply_copy(self, source_id: str, req: CopyRequest, digest: str) -> NetApplyResult:
        self._guard.require_clear()
        target, files = await self._copy_files(source_id, req)
        if self._copy_plan(source_id, target, files).digest != digest:
            raise PreviewChanged(target.name)
        t = await self._pool.get(target)
        checks: list[NetCheck] = []
        async with self._pool.write_lock(target.id):
            for f in files:
                for command, data in write_steps(f):
                    if data is not None:
                        result = await run_audited_upload(
                            t,
                            command,
                            data,
                            name=f"{source_id}:{f.path}",
                            router_id=target.id,
                            screen=SCREEN,
                            guard=self._guard,
                            audit=self._audit,
                        )
                    else:
                        result = await run_audited(
                            t,
                            command,
                            router_id=target.id,
                            screen=SCREEN,
                            guard=self._guard,
                            audit=self._audit,
                        )
                    if not result.ok:
                        reason = (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"
                        return NetApplyResult(
                            target.id, False, False, tuple(checks), f"{command}: {reason}", target.host
                        )
                    if command.startswith(("sha256sum ", "readlink ")):
                        checks.append(_proof(f, result.stdout))
        verified = all(c.ok for c in checks)
        return NetApplyResult(target.id, True, verified, tuple(checks), None, target.host)

    async def save_checklist(self, router_id: str) -> ReflashChecklist:
        rec, t, desc, profile = await self._context(router_id)
        if profile is None:
            raise ValueError(no_match_note(desc.identity.board_name, desc.identity.revision))
        state = await read_discovery(
            t, router_id=rec.id, identity=desc.identity, profile=profile, now=self._clock()
        )
        lost = [
            e for e in (*state.overlay.added, *state.overlay.replaced) if e.path not in state.kept_on_flash
        ]
        checklist = ReflashChecklist(
            router_id=rec.id,
            saved_at=self._clock(),
            profile=profile.key,
            overlay=state.overlay,
            packages_added=state.packages.added,
            lost=await read_files(t, sorted(lost, key=lambda e: e.path), strict=False),
        )
        self.checklists.save(checklist)
        return checklist

    async def refresh_summary(self, rec: RouterRecord) -> None:
        """The poller's hook: once per connect (the cache is cleared on import, delete and flash)."""
        if rec.id in self.summaries:
            return
        try:
            await self.summary(rec.id)
        except (TransportError, ValueError) as exc:
            log.debug("discovery summary of %s failed: %s", rec.id, exc)
