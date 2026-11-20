"""The Tools screen's active pages (v1.2b): previews with a digest, then sessions and one-shot actions."""

from __future__ import annotations

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.tools.sessions import SessionView, ToolPlan, ToolSessions, tool_plan
from openwrtgui.tools.throughput import (
    CPU_WARNING,
    ThroughputRequest,
    iperf3_command,
    parse_iperf3_line,
    server_hint,
)
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
