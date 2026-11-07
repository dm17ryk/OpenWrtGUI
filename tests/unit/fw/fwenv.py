"""The Firewall (and Faults) services against the simulated routers, on one fake clock: the runner's waits and
the simulators' rollback deadlines and timers move together, so a rollback in the sim takes no real time."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from openwrtgui.fw.service import FirewallService
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.net.service import NetworkService
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList, SettingsStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore
from openwrtgui.wifi.service import WifiService

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 5, 21, 4))


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 6, 15, 0)

    def now(self) -> datetime:
        return self.t

    def mono(self) -> float:
        return self.t.timestamp()

    async def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


@dataclass
class FwEnv:
    fw: FirewallService
    net: NetworkService
    wifi: WifiService
    connector: SimConnector
    routers: RouterStore
    guard: BenchGuard
    audit: AuditLog
    pool: ConnectionPool
    settings: SettingsStore
    clock: Clock
    descriptions: dict[str, SelfDescription]
    runner: ApplyRunner
    processes: list[ProcessInfo] = field(default_factory=list)

    def go_live(self) -> None:
        self.processes.append(RUN)
        self.guard.check_local()

    def rec(self, router_id: str) -> RouterRecord:
        rec = self.routers.get(router_id)
        assert rec is not None
        return rec

    async def sim(self, router_id: str) -> Transport:
        rec = self.rec(router_id)
        return await self.connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])

    def audit_lines(self) -> list[str]:
        return [e.command for e in reversed(self.audit.query())]


async def _no_sleep(_: float) -> None:
    return None


async def build(tmp_path: Path) -> FwEnv:
    clock = Clock()
    connector = SimConnector(SIM_DIR, clock=clock.mono)
    routers = RouterStore(tmp_path / "routers.json")
    seed_routers(SIM_DIR, routers)
    processes: list[ProcessInfo] = []
    guard = BenchGuard(GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: processes)
    guard.check_local()

    async def factory(rec: RouterRecord) -> Transport:
        return await connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])

    pool = ConnectionPool(factory)
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    audit = AuditLog(tmp_path / "audit")
    settings = SettingsStore(tmp_path / "settings.json")
    runner = ApplyRunner(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        host_keys=HostKeyStore(tmp_path / "known_hosts"),
        clock=clock.now,
        sleep=clock.sleep,
    )
    wifi = WifiService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        descriptions=descriptions,
        statuses=statuses,
        sleep=_no_sleep,
    )
    net = NetworkService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        descriptions=descriptions,
        statuses=statuses,
        runner=runner,
        wifi=wifi,
        sleep=clock.sleep,
    )
    fw = FirewallService(
        pool=pool,
        routers=routers,
        guard=guard,
        audit=audit,
        settings=settings,
        descriptions=descriptions,
        runner=runner,
        sleep=clock.sleep,
    )
    return FwEnv(
        fw,
        net,
        wifi,
        connector,
        routers,
        guard,
        audit,
        pool,
        settings,
        clock,
        descriptions,
        runner,
        processes,
    )
