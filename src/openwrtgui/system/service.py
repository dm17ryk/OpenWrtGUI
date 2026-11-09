"""The System screen's service: reads, then settings, services, cron, diagnostics, reboot and backup."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.net.apply import (
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    net_plan,
    saved_check,
)
from openwrtgui.paths import DataDir
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.parse import (
    Connection,
    parse_board,
    parse_conntrack,
    parse_rc_list,
    parse_timezones,
    parse_top,
)
from openwrtgui.system.services import ServiceRow, service_rows
from openwrtgui.system.settings import SystemSettings, current_settings, settings_ops
from openwrtgui.system.state import LogEntry, LogKind, ProcessList, SystemOverview, log_entries, read_overview
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show

SCREEN = "System"
UTC = "UTC"
UTC_TZ = "GMT0"  # OpenWrt's own default for zonename UTC (AP2: zonename='UTC', timezone='GMT0')
NO_ZONES = "This router lists no time zones (LuCI's rpcd plugin is missing): only UTC can be chosen"


NO_CONNTRACK = "The connection table is not available: nf_conntrack is not loaded"
DiagTool = Literal["ping", "traceroute", "nslookup"]
_DIAG: dict[str, Callable[[str], str]] = {"ping": s.ping, "traceroute": s.traceroute, "nslookup": s.nslookup}
DIAG_TIMEOUT_S = s.DIAG_LIMIT_S + 5.0  # the router's own `timeout -s KILL` ends it first


class DiagResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: DiagTool
    target: str
    command: str
    output: str  # stdout, then stderr: a bad address is a result, not an error
    exit_status: int


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

    # ---------------------------------------------------------------- diagnostics (D4)
    async def diagnose(self, router_id: str, tool: DiagTool, target: str) -> DiagResult:
        """Run on the router, no preview, audited; refused during a run (traffic from a router under test)."""
        if tool not in _DIAG:
            raise ValueError(f"{tool!r} is not one of {', '.join(_DIAG)}")
        command = _DIAG[tool](target)  # checks the target before anything is sent
        self._guard.require_clear()
        rec, t = await self._transport(router_id)
        done = await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            timeout=DIAG_TIMEOUT_S,
        )
        output = done.stdout + (done.stderr if done.stderr else "")
        return DiagResult(
            tool=tool, target=target, command=command, output=output, exit_status=done.exit_status
        )

    async def _zones(self, t: Transport) -> dict[str, str]:
        return {UTC: UTC_TZ} | parse_timezones(await self._stdout(t, s.TIMEZONES))

    async def zone_strings(self, router_id: str) -> dict[str, str]:
        """Zone name -> TZ string, the router's list plus UTC."""
        _rec, t = await self._transport(router_id)
        return await self._zones(t)

    # ---------------------------------------------------------------- system and time (D5)
    async def _uci(self, t: Transport) -> dict[str, str]:
        result = await t.run(s.UCI_SYSTEM)
        if not result.ok:
            raise ValueError(
                f"The router's system config does not read: {result.stderr.strip() or result.exit_status}"
            )
        return parse_uci_show(result.stdout)

    async def settings(self, router_id: str) -> SystemSettings:
        _rec, t = await self._transport(router_id)
        return current_settings(await self._uci(t))

    async def _settings_plan(
        self, rec: RouterRecord, t: Transport, req: SystemSettings
    ) -> tuple[NetPlan, dict[str, str], dict[str, str]]:
        uci = await self._uci(t)
        zones = await self._zones(t) if req.zonename is not None else {}
        ops, reloads = settings_ops(uci, req, zones)
        plan = net_plan(
            router_id=rec.id, screen=SCREEN, config="system", ops=ops, current=uci, reloads=reloads
        )
        return plan, uci, zones

    async def plan_settings(self, router_id: str, req: SystemSettings) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._settings_plan(rec, t, req))[0]

    async def apply_settings(self, router_id: str, req: SystemSettings, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, uci, zones = await self._settings_plan(rec, t, req)

            async def verify(t2: Transport) -> list[NetCheck]:
                checks = [await saved_check(t2, s.UCI_SYSTEM, plan.ops, uci)]
                if req.hostname is not None:
                    board = parse_board(await self._stdout(t2, s.BOARD))
                    live = board.hostname if board else None
                    checks.append(NetCheck("hostname", live == req.hostname, live or "no answer"))
                if req.zonename is not None:
                    tz = (await self._stdout(t2, s.TZ_FILE)).strip()
                    checks.append(NetCheck("time zone", tz == zones[req.zonename], tz or "no answer"))
                return checks

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def timezones(self, router_id: str) -> TimeZones:
        zones = await self.zone_strings(router_id)
        names = [UTC, *sorted(name for name in zones if name != UTC)]
        return TimeZones(zones=names, note=NO_ZONES if len(names) == 1 else None)
