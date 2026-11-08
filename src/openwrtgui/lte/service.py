"""The LTE screen's service: the state now; actions, the AT console and settings come in later tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.lte.at import find_at_port
from openwrtgui.lte.commands import MODEM_DEVICE
from openwrtgui.lte.state import LteState, read_lte
from openwrtgui.net.service import NetworkService
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "LTE"


class LteService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        net: NetworkService,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._net = net
        self._clock = clock
        self._sleep = sleep
        self._ports: dict[str, tuple[int, str | None]] = {}  # router → (connection, AT port found on it)

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _qmi(self, router_id: str) -> tuple[str, str | None] | None:
        state = await self._net.state(router_id)
        conf = next((v.conf for v in state.interfaces if v.conf is not None and v.conf.proto == "qmi"), None)
        return (conf.name, conf.device) if conf is not None else None

    async def modem_device(self, router_id: str) -> str | None:
        """The qmi interface's device when it is a QMI modem device (`/dev/cdc-wdmN`); None: no LTE here."""
        qmi = await self._qmi(router_id)
        device = qmi[1] if qmi is not None else None
        return device if device is not None and MODEM_DEVICE.fullmatch(device) else None

    async def at_port(self, rec: RouterRecord, t: Transport) -> str | None:
        """D4: found once per connection (a reconnect may follow a modem that re-enumerated)."""
        cached = self._ports.get(rec.id)
        if cached is not None and cached[0] == id(t):
            return cached[1]
        port = await find_at_port(t)
        self._ports[rec.id] = (id(t), port)
        return port

    async def state(self, router_id: str) -> LteState:
        rec = self._record(router_id)
        qmi = await self._qmi(router_id)
        t = await self._pool.get(rec)
        port = await self.at_port(rec, t) if qmi is not None else None
        return await read_lte(t, router_id=rec.id, qmi=qmi, at_port=port, now=self._clock())
