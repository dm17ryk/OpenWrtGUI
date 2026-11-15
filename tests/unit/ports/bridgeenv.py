"""ap5 (v1.0a3 D5) with a clock the simulator and the rollback both follow, so a cut and rpcd's restore happen
in test time."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.net.state import read_network
from openwrtgui.ports.bridge import BridgeState
from openwrtgui.ports.bridge_service import BridgeVlanService
from openwrtgui.ports.bridge_state import read_bridge
from openwrtgui.probe.describe import SelfDescription, describe_router
from openwrtgui.simnet import SimNetwork
from openwrtgui.simulator import SIM_SEED_ENV, SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 15, 21, 4))


@dataclass
class Clock:
    t: datetime = datetime(2026, 11, 15, 10, 0)
    mono: float = 1000.0

    def now(self) -> datetime:
        return self.t

    def monotonic(self) -> float:
        return self.mono

    async def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)
        self.mono += seconds


@dataclass
class BridgeEnv:
    connector: SimConnector
    routers: RouterStore
    guard: BenchGuard
    audit: AuditLog
    pool: ConnectionPool
    runner: ApplyRunner
    clock: Clock
    descriptions: dict[str, SelfDescription] = field(default_factory=dict)
    processes: list[ProcessInfo] = field(default_factory=list)
    service: BridgeVlanService | None = None

    def sim(self, host: str = "192.168.1.7") -> SimNetwork:
        net = self.connector.state(host).net
        assert net is not None
        return net

    def go_live(self) -> None:
        self.processes.append(RUN)
        self.guard.check_local()

    async def state(self, router_id: str) -> BridgeState:
        rec = self.routers.get(router_id)
        assert rec is not None
        t = await self.pool.get(rec)
        desc = self.descriptions.get(rec.id) or await describe_router(t)
        self.descriptions[rec.id] = desc
        net, uci = await read_network(t, rec.id, desc)
        return await read_bridge(t, rec, desc, net, uci)


async def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BridgeEnv:
    monkeypatch.setenv(SIM_SEED_ENV, "ap5")
    clock = Clock()
    connector = SimConnector(SIM_DIR, clock=clock.monotonic)
    routers = RouterStore(tmp_path / "routers.json")
    seed_routers(SIM_DIR, routers)
    processes: list[ProcessInfo] = []
    guard = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: processes)
    guard.check_local()

    async def factory(rec: RouterRecord) -> Transport:
        return await connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])

    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    runner = ApplyRunner(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        host_keys=HostKeyStore(tmp_path / "known_hosts"),
        clock=clock.now,
        sleep=clock.sleep,
    )
    env = BridgeEnv(connector, routers, guard, audit, pool, runner, clock, processes=processes)
    env.service = BridgeVlanService(
        pool=pool, routers=routers, descriptions=env.descriptions, runner=runner, sleep=clock.sleep
    )
    return env
