"""One pooled connection per router, reconnect with backoff, and a write lock per router."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import Transport, TransportError, Unreachable

log = logging.getLogger(__name__)

TransportFactory = Callable[[RouterRecord], Awaitable[Transport]]

BACKOFF_FIRST_S = 5
BACKOFF_MAX_S = 60


@dataclass(frozen=True)
class RouterHealth:
    online: bool
    since: datetime
    error: str | None


def _released() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass
class _Slot:
    transport: Transport | None = None
    failures: int = 0
    retry_at: datetime | None = None
    health: RouterHealth | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connecting: asyncio.Lock = field(default_factory=asyncio.Lock)
    holder: object | None = None
    released: asyncio.Event = field(default_factory=_released)


class ConnectionPool:
    def __init__(self, factory: TransportFactory, clock: Callable[[], datetime] = datetime.now) -> None:
        self._factory = factory
        self._clock = clock
        self._slots: dict[str, _Slot] = {}

    def _slot(self, router_id: str) -> _Slot:
        return self._slots.setdefault(router_id, _Slot())

    def health(self, router_id: str) -> RouterHealth:
        slot = self._slot(router_id)
        if slot.health is None:
            return RouterHealth(online=False, since=self._clock(), error="not connected yet")
        return slot.health

    def write_lock(self, router_id: str) -> asyncio.Lock:
        return self._slot(router_id).lock

    @asynccontextmanager
    async def hold(self, router_id: str) -> AsyncIterator[object]:
        """While a rollback apply waits for its router, everyone else's get() waits: the status poller and the
        screens' reads must not take the connection the apply needs to reach the router and confirm. The
        holder passes the token it gets to its own get() calls."""
        slot = self._slot(router_id)
        while slot.holder is not None:
            await slot.released.wait()
        token = object()
        slot.holder = token
        slot.released.clear()
        try:
            yield token
        finally:
            slot.holder = None
            slot.released.set()

    async def get(self, router: RouterRecord, *, token: object | None = None) -> Transport:
        slot = self._slot(router.id)
        while slot.holder is not None and slot.holder is not token:
            await slot.released.wait()
        async with slot.connecting:
            if slot.transport is not None:
                return slot.transport
            now = self._clock()
            if slot.retry_at is not None and now < slot.retry_at:
                error = slot.health.error if slot.health else "unreachable"
                raise Unreachable(error or "unreachable", retry_at=slot.retry_at)
            try:
                slot.transport = await self._factory(router)
            except TransportError as exc:
                self.mark_failed(router.id, exc)
                raise
            slot.failures = 0
            slot.retry_at = None
            if slot.health is None or not slot.health.online:
                slot.health = RouterHealth(online=True, since=now, error=None)
            return slot.transport

    def mark_failed(self, router_id: str, exc: Exception) -> None:
        """Record a failure: drop the transport and back off before the next attempt."""
        slot = self._slot(router_id)
        now = self._clock()
        slot.transport = None
        slot.failures += 1
        delay = min(BACKOFF_FIRST_S * 2 ** (slot.failures - 1), BACKOFF_MAX_S)
        slot.retry_at = now + timedelta(seconds=delay)
        since = slot.health.since if slot.health is not None and not slot.health.online else now
        slot.health = RouterHealth(online=False, since=since, error=str(exc))
        log.debug("%s unreachable (%s); next try in %s s", router_id, exc, delay)

    async def drop(self, router_id: str) -> None:
        """Close the connection and forget the backoff: the next get() connects at once."""
        slot = self._slot(router_id)
        slot.failures = 0
        slot.retry_at = None
        transport, slot.transport = slot.transport, None
        if transport is not None:
            try:
                await transport.close()
            except (TransportError, OSError):
                log.debug("closing %s failed", router_id, exc_info=True)

    async def close_all(self) -> None:
        for router_id in list(self._slots):
            await self.drop(router_id)
