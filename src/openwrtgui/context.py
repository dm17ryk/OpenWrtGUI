"""Everything one running app needs, built once at start-up."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import httpx

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, psutil_lister
from openwrtgui.live import LiveHub
from openwrtgui.onboard.pc_keys import find_pc_keys, ssh_dirs
from openwrtgui.onboard.wizard import Connector, OnboardService, SshConnector
from openwrtgui.paths import DataDir
from openwrtgui.poller import StatusPoller
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.simulator import SimConnector, seed_routers, sim_http_client, sim_process_lister
from openwrtgui.store.keys import AppKey, load_or_create_app_key
from openwrtgui.store.routers import RouterRecord, RouterStore, router_key_paths
from openwrtgui.store.settings import SettingsStore
from openwrtgui.terminal import TerminalSession
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.update.service import Updater
from openwrtgui.update.versions import parse_version
from openwrtgui.version import APP_VERSION


@dataclass
class AppContext:
    data: DataDir
    settings: SettingsStore
    routers: RouterStore
    app_key: AppKey
    host_keys: HostKeyStore
    pool: ConnectionPool
    guard: BenchGuard
    audit: AuditLog
    onboard: OnboardService
    updater: Updater
    hub: LiveHub
    poller: StatusPoller
    token: str
    port: int
    mode: Literal["real", "simulator"]
    web_dir: Path | None
    statuses: dict[str, RouterStatus] = field(default_factory=dict)
    descriptions: dict[str, SelfDescription] = field(default_factory=dict)
    terminals: set[TerminalSession] = field(default_factory=set)
    quit_event: asyncio.Event = field(default_factory=asyncio.Event)
    exit_command: list[str] | None = None


def _real_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=True, timeout=20.0)


def _find_pc_keys() -> list[Path]:
    return find_pc_keys(ssh_dirs())


def _no_pc_keys() -> list[Path]:
    return []  # the simulator never offers the developer's own keys


def build_context(
    data: DataDir,
    *,
    token: str,
    port: int,
    simulator: Path | None,
    web_dir: Path | None,
    install_dir: Path | None = None,
) -> AppContext:
    settings = SettingsStore(data.settings_file)
    current = settings.load()
    routers = RouterStore(data.routers_file)
    app_key = load_or_create_app_key(data.keys_dir)
    host_keys = HostKeyStore(data.known_hosts_file)
    audit = AuditLog(data.audit_dir)
    audit.prune(current.audit_retention_days, date.today())

    connector: Connector
    client_factory: Callable[[], httpx.AsyncClient]
    pc_keys: Callable[[], Sequence[Path]]
    if simulator is not None:
        sim = SimConnector(simulator)
        connector = sim
        pc_keys = _no_pc_keys
        seed_routers(simulator, routers)
        guard = BenchGuard(current.guard, lister=sim_process_lister, use_lock_files=False)

        async def factory(rec: RouterRecord) -> Transport:
            return await sim.connect(
                rec.host, rec.port, password=None, key_paths=router_key_paths(rec, app_key.private_path)
            )

        def client_factory() -> httpx.AsyncClient:
            return sim_http_client(simulator)

    else:
        connector = SshConnector(host_keys)
        guard = BenchGuard(current.guard, lister=psutil_lister)
        pc_keys = _find_pc_keys

        async def factory(rec: RouterRecord) -> Transport:
            return await SshTransport.connect(
                rec.host,
                rec.port,
                rec.username,
                host_keys=host_keys,
                key_paths=router_key_paths(rec, app_key.private_path),
            )

        client_factory = _real_http_client

    pool = ConnectionPool(factory)
    hub = LiveHub()
    statuses: dict[str, RouterStatus] = {}
    descriptions: dict[str, SelfDescription] = {}
    onboard = OnboardService(
        connector=connector,
        host_keys=host_keys,
        app_key=app_key,
        routers=routers,
        guard=guard,
        audit=audit,
        pool=pool,
        pc_keys=pc_keys,
    )
    updater = Updater(
        settings=settings,
        updates_dir=data.updates_dir,
        current=parse_version(APP_VERSION),
        client_factory=client_factory,
        install_dir=install_dir,
        hub=hub,
    )
    poller = StatusPoller(
        routers=routers, pool=pool, guard=guard, hub=hub, statuses=statuses, descriptions=descriptions
    )
    return AppContext(
        data=data,
        settings=settings,
        routers=routers,
        app_key=app_key,
        host_keys=host_keys,
        pool=pool,
        guard=guard,
        audit=audit,
        onboard=onboard,
        updater=updater,
        hub=hub,
        poller=poller,
        token=token,
        port=port,
        mode="simulator" if simulator is not None else "real",
        web_dir=web_dir,
        statuses=statuses,
        descriptions=descriptions,
    )
