"""The Tools screen's active pages (v1.2b): previews with a digest, then sessions and one-shot actions."""

from __future__ import annotations

import contextlib

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.tools.sessions import SCREEN, SessionView, ToolPlan, ToolSessions, tool_plan
from openwrtgui.tools.throughput import (
    CPU_WARNING,
    ThroughputRequest,
    iperf3_command,
    parse_iperf3_line,
    server_hint,
)
from openwrtgui.tools.traffic import (
    SEND_LIMIT_S,
    ListenRequest,
    SendRequest,
    SendResult,
    listen_command,
    listen_parser,
    send_command,
    send_result,
)
from openwrtgui.transport.base import TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged, WifiService


class ToolsService:
    def __init__(
        self,
        *,
        sessions: ToolSessions,
        routers: RouterStore,
        pool: ConnectionPool,
        guard: BenchGuard,
        audit: AuditLog,
        wifi: WifiService,
    ) -> None:
        self._sessions = sessions
        self._routers = routers
        self._pool = pool
        self._guard = guard
        self._audit = audit
        self._wifi = wifi

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    def _checked(self, rec: RouterRecord, plan: ToolPlan, digest: str) -> None:
        if plan.digest != digest:
            raise PreviewChanged(rec.name)

    # ---------------------------------------------------------------- Throughput
    def throughput_plan(self, router_id: str, req: ThroughputRequest) -> ToolPlan:
        rec = self._record(router_id)
        command, _limit = iperf3_command(req)
        warnings = [CPU_WARNING]
        if req.mode == "server":
            warnings.append(server_hint(rec.host, req.port))
        return tool_plan([command], warnings)

    async def throughput_start(self, router_id: str, req: ThroughputRequest, digest: str) -> SessionView:
        rec = self._record(router_id)
        self._checked(rec, self.throughput_plan(router_id, req), digest)
        command, limit = iperf3_command(req)
        return await self._sessions.start(
            rec.id,
            kind="throughput",
            title="Throughput",
            command=command,
            limit_s=limit,
            parse=parse_iperf3_line,
        )

    # ---------------------------------------------------------------- Traffic generator
    def listen_plan(self, router_id: str, req: ListenRequest) -> ToolPlan:
        self._record(router_id)
        command, _limit = listen_command(req)
        return tool_plan([command], [])

    async def listen_start(self, router_id: str, req: ListenRequest, digest: str) -> SessionView:
        rec = self._record(router_id)
        self._checked(rec, self.listen_plan(router_id, req), digest)
        command, limit = listen_command(req)
        return await self._sessions.start(
            rec.id,
            kind="listen",
            title="Traffic listen",
            command=command,
            limit_s=limit,
            parse=listen_parser(),
        )

    def send_plan(self, router_id: str, req: SendRequest) -> ToolPlan:
        self._record(router_id)
        return tool_plan([send_command(req)], [])

    async def send(self, router_id: str, req: SendRequest, digest: str) -> SendResult:
        """One command on its own connection, outside the write lock: it changes no config, and a 30 s send
        must not hold up an apply (R6)."""
        rec = self._record(router_id)
        self._guard.require_clear()
        plan = self.send_plan(router_id, req)
        self._checked(rec, plan, digest)
        own = await self._pool.fresh(rec)
        try:
            result = await run_audited(
                own,
                plan.lines[0],
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                timeout=SEND_LIMIT_S + 5,
            )
        finally:
            with contextlib.suppress(TransportError, OSError):
                await own.close()
        return send_result(req, result)
