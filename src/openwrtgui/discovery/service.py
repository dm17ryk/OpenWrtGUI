"""Discovery per router: the state read, and (later tasks) the firmware check, copies, tools and services."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from datetime import datetime

from openwrtgui.discovery.state import DiscoveryState, read_discovery
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.images.store import ProfileStore
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Discovery"


class DiscoveryService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        descriptions: MutableMapping[str, SelfDescription],
        profiles: ProfileStore,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._descriptions = descriptions
        self._profiles = profiles
        self._clock = clock

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

    async def state(self, router_id: str) -> DiscoveryState:
        rec = self._record(router_id)
        t = await self._pool.get(rec)
        identity = (await self._described(rec, t)).identity
        profile = self._profiles.match(identity.board_name, identity.revision)
        return await read_discovery(
            t, router_id=rec.id, identity=identity, profile=profile, now=self._clock()
        )
