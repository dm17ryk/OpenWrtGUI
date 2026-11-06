from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.luci_bridge.service import LuciBridgeService
from openwrtgui.luci_bridge.upstream import Upstream, sim_upstream
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.simulator import SimConnector, seed_routers
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import CommandResult, Transport, TransportError
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.transport.pool import ConnectionPool

SIM_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "sim"
RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 5, 21, 4))


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 9, 0, 0)

    def __call__(self) -> datetime:
        return self.now


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.connector = SimConnector(SIM_DIR)
        self.routers = RouterStore(tmp_path / "routers.json")
        seed_routers(SIM_DIR, self.routers)
        self.processes: list[ProcessInfo] = []
        self.guard = BenchGuard(
            GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: self.processes
        )
        self.guard.check_local()
        self.audit = AuditLog(tmp_path / "audit")
        self.clock = Clock()
        self.transports: list[ReplayTransport] = []

        async def factory(rec: RouterRecord) -> Transport:
            t = await self.connector.connect(rec.host, rec.port, password=None, key_paths=[Path("k")])
            assert isinstance(t, ReplayTransport)
            self.transports.append(t)
            return t

        self.pool = ConnectionPool(factory)
        self.descriptions: dict[str, SelfDescription] = {}

        async def upstream(rec: RouterRecord, t: Transport):  # type: ignore[no-untyped-def]
            return await sim_upstream(lambda path: path.rsplit("/", 1)[-1])

        self.service = LuciBridgeService(
            pool=self.pool,
            routers=self.routers,
            guard=self.guard,
            audit=self.audit,
            descriptions=self.descriptions,
            upstream_factory=upstream,
            clock=self.clock,
        )

    def go_live(self) -> None:
        self.processes.append(RUN)
        self.guard.check_local()

    def calls(self) -> list[str]:
        return [c for t in self.transports for c in t.calls]

    def audit_lines(self) -> list[str]:
        return [e.command for e in reversed(self.audit.query())]


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    e = Env(tmp_path)
    yield e
    await e.service.close_all()


async def _fetch(url: str) -> httpx.Response:
    async with httpx.AsyncClient(follow_redirects=True) as c:
        return await c.get(url)


async def test_pages_list_with_native_marks(env: Env) -> None:
    pages = {p.path: p for p in await env.service.pages("ap1")}
    assert (
        pages["admin/network/wireless"].native == "wifi" and pages["admin/network/dhcp"].native == "network"
    )
    assert pages["admin/network/firewall/zones"].native == "firewall"  # native since v0.4


async def test_open_and_close_record_changes(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/dhcp")
    assert view.access == "write" and view.page.title == "DHCP"
    page = await _fetch(view.url)
    assert page.status_code == 200 and "LuCI (simulated): dhcp" in page.text and "session sim-1" in page.text
    assert any(c.startswith("ubus call session grant ") for c in env.calls())
    t = env.transports[0]
    await t.run("uci set wireless.radio0.channel='11'\nuci commit wireless")
    changes = await env.service.changes(view.id)
    assert [(c.option, c.before, c.after) for c in changes] == [("wireless.radio0.channel", "1", "11")]
    closed = await env.service.close(view.id)
    assert closed.changes == changes
    assert 'ubus call session destroy \'{"ubus_rpc_session":"<hidden>"}\'' in env.audit_lines()
    assert env.audit_lines()[-1] == "LuCI page admin/network/dhcp closed; changed wireless.radio0.channel"
    assert any(line.startswith("LuCI page admin/network/dhcp opened (write)") for line in env.audit_lines())
    with pytest.raises(KeyError):
        await env.service.changes(view.id)


async def test_secrets_in_a_luci_diff_are_hidden(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    await env.transports[0].run("uci set wireless.default_radio0.key='new-lab-key'\nuci commit wireless")
    [change] = await env.service.changes(view.id)
    assert change.option == "wireless.default_radio0.key" and change.after == "<hidden>"


def test_wireguard_keys_in_a_luci_diff_are_hidden() -> None:
    from openwrtgui.luci_bridge.service import diff_uci

    [change] = diff_uci({}, {"network.wg0.private_key": "aGVsbG8="})
    assert change.after == "<hidden>"


async def test_session_ids_never_reach_the_audit_log(env: Env) -> None:
    await env.service.open("ap1", "admin/network/wireless")
    assert not any("sim-1" in line for line in env.audit_lines())


async def test_opened_read_only_during_a_run(env: Env) -> None:
    env.go_live()
    view = await env.service.open("ap1", "admin/network/wireless")
    assert view.access == "read"
    grants = [c for c in env.calls() if c.startswith("ubus call session grant ")]
    assert all('"write"' not in c for c in grants)


async def test_guard_live_downgrades_open_bridge(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    env.go_live()
    await env.service.tick()
    assert env.service.view(view.id).access == "read"
    page = await _fetch(view.url)
    assert "session sim-2" in page.text
    assert 'ubus call session destroy \'{"ubus_rpc_session":"<hidden>"}\'' in env.audit_lines()
    assert (
        "LuCI page admin/network/wireless switched to read-only: Bench Guard went live" in env.audit_lines()
    )


async def test_bridge_closes_when_guard_live_and_no_read_session(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    env.go_live()
    t = env.transports[0]

    async def lost(command: str, *, timeout: float = 15.0) -> CommandResult:
        raise TransportError("connection lost")

    t.run = lost  # type: ignore[method-assign]
    await env.service.tick()
    with pytest.raises(KeyError):
        env.service.view(view.id)
    with pytest.raises(httpx.ConnectError):
        await _fetch(view.url)


async def test_downgrade_closes_the_bridge_when_the_write_session_survives(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    env.go_live()
    t = env.transports[0]
    real_run = t.run

    async def destroy_refused(command: str, *, timeout: float = 15.0) -> CommandResult:
        if command.startswith("ubus call session destroy"):
            return CommandResult(command, "", "Command failed: Permission denied", 4)
        return await real_run(command, timeout=timeout)

    t.run = destroy_refused  # type: ignore[method-assign]
    await env.service.tick()
    with pytest.raises(KeyError):
        env.service.view(view.id)  # fail closed: the page cannot keep using the write session
    with pytest.raises(httpx.ConnectError):
        await _fetch(view.url)


async def test_a_failed_open_leaves_no_session_behind(env: Env) -> None:
    async def broken(rec: RouterRecord, t: Transport) -> Upstream:
        raise TransportError("this connection cannot forward a port to the router's web server")

    service = LuciBridgeService(
        pool=env.pool,
        routers=env.routers,
        guard=env.guard,
        audit=env.audit,
        descriptions=env.descriptions,
        upstream_factory=broken,
        clock=env.clock,
    )
    with pytest.raises(TransportError):
        await service.open("ap1", "admin/network/dhcp")
    assert 'ubus call session destroy \'{"ubus_rpc_session":"<hidden>"}\'' in env.audit_lines()
    assert env.calls()[-1].startswith("ubus call session destroy")


async def test_write_grants_are_refused_once_a_run_is_live(env: Env) -> None:
    clear = env.guard.state()
    env.go_live()
    answers = iter([clear])  # the access decision still saw no run; the grants come after it started
    real_state = env.guard.state
    env.guard.state = lambda: next(answers, None) or real_state()  # type: ignore[method-assign]
    with pytest.raises(GuardLocked):
        await env.service.open("ap1", "admin/network/dhcp")
    grants = [c for c in env.calls() if c.startswith("ubus call session grant ")]
    assert all('"write"' not in c for c in grants)
    assert env.calls()[-1].startswith("ubus call session destroy")


async def test_view_follows_the_downgrade(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    assert env.service.view(view.id).access == "write"
    env.go_live()
    await env.service.tick()
    assert env.service.view(view.id).access == "read" and env.service.view(view.id).url == view.url


async def test_idle_bridge_is_closed_and_session_destroyed(env: Env) -> None:
    view = await env.service.open("ap1", "admin/network/wireless")
    env.clock.now += timedelta(seconds=301)
    await env.service.tick()
    with pytest.raises(KeyError):
        env.service.view(view.id)
    assert env.audit_lines()[-1].startswith("LuCI page admin/network/wireless closed")


async def test_unknown_page_is_refused(env: Env) -> None:
    with pytest.raises(ValueError, match="No LuCI page admin/nope on AP1 · bench"):
        await env.service.open("ap1", "admin/nope")
