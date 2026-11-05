from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus, read_status
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import WifiService

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 5, 21, 4))


@dataclass
class WifiEnv:
    service: WifiService
    connector: SimConnector
    routers: RouterStore
    guard: BenchGuard
    audit: AuditLog
    pool: ConnectionPool
    statuses: dict[str, RouterStatus]
    processes: list[ProcessInfo] = field(default_factory=list)
    wrap: list[Callable[[Transport], Transport]] = field(default_factory=list)

    def go_live(self) -> None:
        self.processes.append(RUN)
        self.guard.check_local()

    async def sim(self, router_id: str) -> Transport:
        rec = self.routers.get(router_id)
        assert rec is not None
        return await self.connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])

    def audit_lines(self) -> list[tuple[str, str]]:
        return [(e.command, e.source) for e in reversed(self.audit.query())]


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def env(tmp_path: Path) -> WifiEnv:
    connector = SimConnector(SIM_DIR)
    routers = RouterStore(tmp_path / "routers.json")
    seed_routers(SIM_DIR, routers)
    processes: list[ProcessInfo] = []
    guard = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: processes)
    guard.check_local()
    holder: dict[str, Any] = {}

    async def factory(rec: RouterRecord) -> Transport:
        t: Transport = await connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])
        for wrap in holder["env"].wrap:
            t = wrap(t)
        return t

    pool = ConnectionPool(factory)
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    audit = AuditLog(tmp_path / "audit")
    service = WifiService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        descriptions=descriptions,
        statuses=statuses,
        sleep=_no_sleep,
    )
    env = WifiEnv(service, connector, routers, guard, audit, pool, statuses, processes)
    holder["env"] = env
    statuses["ap1"] = await read_status(await env.sim("ap1"))
    return env
