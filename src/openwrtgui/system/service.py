"""The System screen's service: reads, then settings, services, cron, diagnostics, reboot and backup."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.paths import DataDir
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.parse import Connection, parse_conntrack, parse_rc_list, parse_timezones, parse_top
from openwrtgui.system.services import ServiceRow, service_rows
from openwrtgui.system.state import LogEntry, LogKind, ProcessList, SystemOverview, log_entries, read_overview
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "System"
UTC = "UTC"
UTC_TZ = "GMT0"  # OpenWrt's own default for zonename UTC (AP2: zonename='UTC', timezone='GMT0')
NO_ZONES = "This router lists no time zones (LuCI's rpcd plugin is missing): only UTC can be chosen"


NO_CONNTRACK = "The connection table is not available: nf_conntrack is not loaded"


class Connections(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[Connection]  # at most 500 (AP2 has ~7 MB free RAM)
    note: str | None = None


class TimeZones(BaseModel):
    model_config = ConfigDict(frozen=True)

    zones: list[str]  # UTC first (the router's list has none: LuCI adds it), then the router's, sorted
    note: str | None = None


class SystemService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        runner: ApplyRunner,
        data: DataDir,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._runner = runner
        self._data = data
        self._clock = clock
        self._sleep = sleep

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _transport(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._record(router_id)
        return rec, await self._pool.get(rec)

    async def _stdout(self, t: Transport, command: str) -> str:
        result = await t.run(command)
        return result.stdout if result.ok else ""

    # ---------------------------------------------------------------- reads (they work during a run)
    async def overview(self, router_id: str) -> SystemOverview:
        rec, t = await self._transport(router_id)
        return await read_overview(t, router_id=rec.id, now=self._clock())

    async def logs(self, router_id: str, kind: LogKind, lines: s.LogLength) -> list[LogEntry]:
        read = s.logread(lines)  # checks the length for both logs
        command = read if kind == "system" else s.DMESG
        _rec, t = await self._transport(router_id)
        entries = log_entries(await self._stdout(t, command), kind)
        return entries if kind == "system" else entries[-lines:]

    async def processes(self, router_id: str) -> ProcessList:
        _rec, t = await self._transport(router_id)
        rows, cpu, column = parse_top(await self._stdout(t, s.TOP))
        return ProcessList(rows=rows, cpu=cpu, column=column)

    async def services(self, router_id: str) -> list[ServiceRow]:
        _rec, t = await self._transport(router_id)
        return service_rows(parse_rc_list(await self._stdout(t, s.RC_LIST)))

    async def connections(self, router_id: str) -> Connections:
        _rec, t = await self._transport(router_id)
        result = await t.run(s.CONNTRACK)
        if not result.ok:
            return Connections(rows=[], note=NO_CONNTRACK)
        return Connections(rows=parse_conntrack(result.stdout))

    async def zone_strings(self, router_id: str) -> dict[str, str]:
        """Zone name -> TZ string, the router's list plus UTC."""
        _rec, t = await self._transport(router_id)
        return {UTC: UTC_TZ} | parse_timezones(await self._stdout(t, s.TIMEZONES))

    async def timezones(self, router_id: str) -> TimeZones:
        zones = await self.zone_strings(router_id)
        names = [UTC, *sorted(name for name in zones if name != UTC)]
        return TimeZones(zones=names, note=NO_ZONES if len(names) == 1 else None)
