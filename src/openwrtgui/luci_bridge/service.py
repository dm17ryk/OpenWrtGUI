"""LuCI fallback pages (spec 7.14): open a bridge, follow Bench Guard and idleness, report what changed."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, MutableMapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.secrets import shown
from openwrtgui.guard.writes import run_audited
from openwrtgui.luci_bridge.depends import (
    UNCHECKED,
    Facts,
    dir_paths,
    files_command,
    fs_paths,
    listing_command,
    missing_paths,
    parse_ls,
    uci_command,
    uci_configs,
    usable_groups,
)
from openwrtgui.luci_bridge.pages import PageView, page_views
from openwrtgui.luci_bridge.proxy import BridgeProxy
from openwrtgui.luci_bridge.session import (
    Access,
    create_command,
    destroy_command,
    grant_commands,
    page_groups,
    set_command,
)
from openwrtgui.luci_bridge.upstream import Upstream
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.probe.luci_menu import LuciPage
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show, parse_uci_show_raw

log = logging.getLogger(__name__)

SCREEN = "LuCI"
UCI_SHOW = "uci show"
FACTS_TTL = timedelta(seconds=60)  # how long the answers to a router's menu `depends` are kept (v1.0a1 D3)
UpstreamFactory = Callable[[RouterRecord, Transport], Awaitable[Upstream]]


@dataclass(frozen=True)
class BridgeView:
    id: str
    router_id: str
    page: PageView
    url: str
    access: Access
    opened_at: datetime


@dataclass(frozen=True)
class UciChange:
    option: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class BridgeClosed:
    id: str
    changes: tuple[UciChange, ...]


@dataclass
class _Bridge:
    view: BridgeView
    rec: RouterRecord
    transport: Transport
    page: LuciPage
    sid: str
    proxy: BridgeProxy
    upstream: Upstream
    before: dict[str, str]
    last_used: datetime


def diff_uci(before: dict[str, str], after: dict[str, str]) -> tuple[UciChange, ...]:
    """Options that changed; values of secret options are hidden."""
    changes = []
    for option in sorted(set(before) | set(after)):
        old, new = before.get(option), after.get(option)
        if old == new:
            continue
        changes.append(UciChange(option, shown(option, old), shown(option, new)))
    return tuple(changes)


class LuciBridgeService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        descriptions: MutableMapping[str, SelfDescription],
        upstream_factory: UpstreamFactory,
        clock: Callable[[], datetime] = datetime.now,
        idle_s: float = 300.0,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._descriptions = descriptions
        self._upstream_factory = upstream_factory
        self._clock = clock
        self._idle = timedelta(seconds=idle_s)
        self._bridges: dict[str, _Bridge] = {}
        # router id -> (read at, the description read for, facts); a new description reads them again
        self._facts: dict[str, tuple[datetime, SelfDescription | None, Facts]] = {}
        # v1.0c Task 4: the read in flight per router, shared by every caller (#54), and a count of the app's
        # changes per router, so a read a change overtook is answered but not kept
        # the read in flight per router, with the description it was made for (#77 minor 7)
        self._facts_reads: dict[str, tuple[SelfDescription | None, asyncio.Future[Facts]]] = {}
        self._facts_gen: dict[str, int] = {}

    async def _connect(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec, await self._pool.get(rec)

    async def _luci_pages(self, rec: RouterRecord, t: Transport) -> tuple[LuciPage, ...]:
        desc = self._descriptions.get(rec.id)
        if desc is None:
            desc = await describe_router(t)
            self._descriptions[rec.id] = desc
        return desc.luci.pages if desc.luci else ()

    def _acl(self, router_id: str) -> dict[str, dict[str, Any]]:
        desc = self._descriptions.get(router_id)
        return desc.luci.acl if desc and desc.luci else {}

    async def _read_facts(self, rec: RouterRecord, t: Transport, pages: Sequence[LuciPage]) -> Facts:
        """What the router's menu asks about (D3); facts the router cannot give hide nothing."""
        paths = fs_paths(pages)
        try:
            files: dict[str, str] = {}
            if paths:
                listed = await t.run(files_command(paths))
                files = parse_ls(listed.stdout)
                if set(files) | missing_paths(listed.stderr, paths) != set(paths):
                    return UNCHECKED  # an ls that cannot say (no -L, not found, refused)
            for path in dir_paths(pages):
                if files.get(path) == "directory":
                    shown = await t.run(listing_command(path))
                    files[path] = "directory" if shown.ok and shown.stdout.strip() else "empty directory"
            uci: dict[str, dict[str, str]] = {}
            for config in uci_configs(pages):
                done = await t.run(uci_command(config))
                if done.ok:  # `uci -q show` of a config that does not exist fails: it is absent
                    uci[config] = parse_uci_show_raw(done.stdout)  # values as printed (v1.0b2 D3c)
        except TransportError:
            return UNCHECKED
        acl = self._acl(rec.id)  # empty: the router's acl.d could not be read, so access is not checked
        return Facts(files, uci, usable_groups(acl) if acl else None)

    async def _page_facts(self, rec: RouterRecord, t: Transport, pages: Sequence[LuciPage]) -> Facts:
        desc = self._descriptions.get(rec.id)
        cached = self._facts.get(rec.id)
        if cached is not None and cached[1] is desc and self._clock() - cached[0] < FACTS_TTL:
            return cached[2]
        shared = self._facts_reads.get(rec.id)
        if shared is not None and shared[0] is desc:
            read = shared[1]
        else:  # none, or one made for an older page list: never shared with this caller (#77 minor 7)
            read = asyncio.ensure_future(self._read_facts(rec, t, pages))
            self._facts_reads[rec.id] = (desc, read)
            gen = self._facts_gen.get(rec.id, 0)
            read.add_done_callback(lambda done: self._facts_read(rec.id, done, desc, gen))
        return await asyncio.shield(read)  # one caller giving up does not end the read for the others

    def _facts_read(
        self, router_id: str, done: asyncio.Future[Facts], desc: SelfDescription | None, gen: int
    ) -> None:
        """Keep a finished read only when it is whole and no change of the app's overtook it."""
        shared = self._facts_reads.get(router_id)
        if shared is not None and shared[1] is done:
            del self._facts_reads[router_id]
        if done.cancelled() or done.exception() is not None:
            return
        facts = done.result()
        overtaken = self._facts_gen.get(router_id, 0) != gen or self._descriptions.get(router_id) is not desc
        if facts.checked and not overtaken:
            self._facts[router_id] = (self._clock(), desc, facts)

    def forget_facts(self, router_id: str) -> None:
        """The app changed the router's config (v1.0a2 D10a): the next page list asks it again, and a read
        already in flight is not kept (v1.0c Task 4)."""
        self._facts.pop(router_id, None)
        self._facts_reads.pop(router_id, None)
        self._facts_gen[router_id] = self._facts_gen.get(router_id, 0) + 1

    async def pages(self, router_id: str) -> list[PageView]:
        rec, t = await self._connect(router_id)
        pages = await self._luci_pages(rec, t)
        return page_views(pages, await self._page_facts(rec, t, pages))

    def view(self, bridge_id: str) -> BridgeView:
        return self._bridges[bridge_id].view

    async def _run(
        self,
        t: Transport,
        rec: RouterRecord,
        command: str,
        secret: tuple[str, ...],
        *,
        require_guard: bool = False,
    ) -> str:
        # rpcd sessions live in memory and change no config, so a read-only one is fine during a run;
        # granting write access is not (require_guard).
        result = await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            source="app",
            secrets=secret,
            require_guard=require_guard,
        )
        if not result.ok:
            raise TransportError(
                f"The router refused the LuCI session: {(result.stderr or result.stdout).strip()}"
            )
        return result.stdout

    async def _new_session(self, rec: RouterRecord, t: Transport, page: LuciPage, access: Access) -> str:
        created = json.loads(await self._run(t, rec, create_command(), ()) or "{}")
        sid = str(created["ubus_rpc_session"])
        try:
            token = secrets.token_hex(16)
            acl = self._acl(rec.id)
            for command in grant_commands(sid, page_groups(page, acl), acl, access):
                await self._run(t, rec, command, (sid,), require_guard=access == "write")
            await self._run(t, rec, set_command(sid, token), (sid, token))
        except BaseException:
            await self._destroy_sid(t, rec, sid)
            raise
        return sid

    async def _destroy_sid(self, t: Transport, rec: RouterRecord, sid: str, *, strict: bool = False) -> None:
        try:
            await self._run(t, rec, destroy_command(sid), (sid,))
        except TransportError as exc:
            if strict:
                raise
            log.info("LuCI session on %s not destroyed: %s", rec.id, exc)  # it expires after 5 min idle

    async def _destroy(self, b: _Bridge, sid: str) -> None:
        await self._destroy_sid(b.transport, b.rec, sid)

    async def open(self, router_id: str, path: str) -> BridgeView:
        rec, t = await self._connect(router_id)
        pages = await self._luci_pages(rec, t)
        page = next((p for p in pages if p.path == path), None)
        if page is None:
            raise ValueError(f"No LuCI page {path} on {rec.name}")
        shown = next(v for v in page_views(pages, await self._page_facts(rec, t, pages)) if v.path == path)
        if not shown.available:
            raise ValueError(f"LuCI does not show {shown.label} on {rec.name}: {shown.missing}")
        access: Access = "read" if self._guard.state().live else "write"
        before = parse_uci_show((await t.run(UCI_SHOW)).stdout)
        sid = await self._new_session(rec, t, page, access)
        bridge_id = secrets.token_hex(8)
        secret = secrets.token_urlsafe(24)
        upstream: Upstream | None = None
        proxy: BridgeProxy | None = None
        try:
            upstream = await self._upstream_factory(rec, t)
            proxy = BridgeProxy(
                upstream_port=upstream.port,
                secret=secret,
                sid=sid,
                on_use=lambda: self._touch(bridge_id),
                scheme=upstream.scheme,
            )
            port = await proxy.start()
        except BaseException:  # leave nothing behind: no session, no SSH forward, no listener
            await self._destroy_sid(t, rec, sid)
            if proxy is not None:
                await proxy.stop()
            if upstream is not None:
                await upstream.close()
            raise
        now = self._clock()
        view = BridgeView(
            id=bridge_id,
            router_id=rec.id,
            page=shown,
            url=f"http://127.0.0.1:{port}/__owg/enter?k={secret}&to=/cgi-bin/luci/{page.path}",
            access=access,
            opened_at=now,
        )
        self._bridges[bridge_id] = _Bridge(view, rec, t, page, sid, proxy, upstream, before, now)
        self._audit.record(
            router=rec.id,
            screen=SCREEN,
            command=f"LuCI page {path} opened ({access})",
            exit_status=None,
            source="user",
        )
        return view

    def _touch(self, bridge_id: str) -> None:
        b = self._bridges.get(bridge_id)
        if b is not None:
            b.last_used = self._clock()

    async def changes(self, bridge_id: str) -> tuple[UciChange, ...]:
        b = self._bridges[bridge_id]
        return diff_uci(b.before, parse_uci_show((await b.transport.run(UCI_SHOW)).stdout))

    async def close(self, bridge_id: str) -> BridgeClosed:
        b = self._bridges.pop(bridge_id)
        try:
            changes = diff_uci(b.before, parse_uci_show((await b.transport.run(UCI_SHOW)).stdout))
        except TransportError:
            changes = ()
        await self._destroy(b, b.sid)
        await b.proxy.stop()
        await b.upstream.close()
        changed = ", ".join(c.option for c in changes) or "nothing"
        self._audit.record(
            router=b.rec.id,
            screen=SCREEN,
            command=f"LuCI page {b.page.path} closed; changed {changed}",
            exit_status=None,
            source="user",
        )
        return BridgeClosed(bridge_id, changes)

    async def tick(self) -> None:
        """Close idle bridges; make writable ones read-only as soon as Bench Guard sees a run."""
        now = self._clock()
        live = self._guard.state().live
        for bridge_id, b in list(self._bridges.items()):
            if now - b.last_used > self._idle:
                await self.close(bridge_id)
            elif live and b.view.access == "write":
                try:
                    await self._downgrade(b)
                except TransportError as exc:  # no read-only session to switch to, so the page goes
                    log.warning("LuCI page on %s closed: no read-only session (%s)", b.rec.id, exc)
                    await self.close(bridge_id)

    async def _downgrade(self, b: _Bridge) -> None:
        old = b.sid
        b.sid = await self._new_session(b.rec, b.transport, b.page, "read")
        b.proxy.set_sid(b.sid)
        b.view = replace(b.view, access="read")
        # strict: if the write session survives, the caller closes the bridge (fail closed)
        await self._destroy_sid(b.transport, b.rec, old, strict=True)
        self._audit.record(
            router=b.rec.id,
            screen=SCREEN,
            command=f"LuCI page {b.page.path} switched to read-only: Bench Guard went live",
            exit_status=None,
            source="app",
        )

    async def close_all(self) -> None:
        for bridge_id in list(self._bridges):
            await self.close(bridge_id)
