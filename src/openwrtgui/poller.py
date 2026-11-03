"""Background loop: router status every few seconds, Bench Guard every two."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.live import LiveHub
from openwrtgui.probe.status import RouterStatus, read_status, ssids_on_air
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import TransportError
from openwrtgui.transport.pool import ConnectionPool

log = logging.getLogger(__name__)


class StatusPoller:
    def __init__(
        self,
        *,
        routers: RouterStore,
        pool: ConnectionPool,
        guard: BenchGuard,
        hub: LiveHub,
        statuses: dict[str, RouterStatus],
        interval_s: float = 5.0,
        guard_interval_s: float = 2.0,
    ) -> None:
        self.routers = routers
        self.pool = pool
        self.guard = guard
        self.hub = hub
        self.statuses = statuses
        self.interval_s = interval_s
        self.guard_interval_s = guard_interval_s
        self._last_guard: tuple[bool, tuple[str, ...]] | None = None

    def _offline(self, rec: RouterRecord) -> None:
        self.statuses.pop(rec.id, None)
        self.guard.set_router_signs(rec.id, [])
        health = self.pool.health(rec.id)
        self.hub.publish(
            {
                "type": "router-offline",
                "router": rec.id,
                "since": health.since.isoformat(),
                "error": health.error,
            }
        )

    async def poll_router(self, rec: RouterRecord) -> None:
        try:
            transport = await self.pool.get(rec)
        except TransportError:
            self._offline(rec)
            return
        try:
            status = await read_status(transport)
        except (TransportError, ValueError) as exc:
            log.debug("reading %s failed: %s", rec.id, exc)
            self.pool.mark_failed(rec.id, exc)
            self._offline(rec)
            return
        self.statuses[rec.id] = status
        self.guard.set_router_signs(rec.id, ssids_on_air(status))
        self.hub.publish({"type": "status", "router": rec.id, "status": status})

    async def poll_all(self) -> None:
        records = [r for r in self.routers.list() if r.auth == "key"]
        await asyncio.gather(*(self.poll_router(r) for r in records))

    async def check_guard(self) -> None:
        state = self.guard.check_local()
        key = (state.live, tuple(r.text for r in state.reasons))
        if key != self._last_guard:
            self._last_guard = key
            self.hub.publish({"type": "guard", "state": state})

    async def run(self, stop: asyncio.Event) -> None:
        async def loop(interval: float, step: Callable[[], Awaitable[None]]) -> None:
            while not stop.is_set():
                try:
                    await step()
                except Exception:
                    log.exception("background step failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), interval)

        await asyncio.gather(
            loop(self.guard_interval_s, self.check_guard), loop(self.interval_s, self.poll_all)
        )
