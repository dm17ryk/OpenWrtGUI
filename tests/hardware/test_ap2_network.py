"""AP2 network window: changes applied the way the app applies them, on the real router, and undone.

uv run pytest -m hardware tests/hardware/test_ap2_network.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved and the txctl session was told of (about 6 minutes; AP2 is at
192.168.1.12, or does not answer for up to about 65 s while a change rolls back). Each test undoes its change
through the app; the fixture then waits for AP2 at 192.168.1.2 and checks that network, dhcp, the radio, the
switch ports and the mirror are as found. The app's host-key store is a copy of --known-hosts in the test's
temp folder: following lan to .12 pins the same key for .12 there, never in the user's file.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import ApplyRunner, NetApplyResult
from openwrtgui.net.dns import DnsRequest
from openwrtgui.net.interfaces import InterfaceRequest
from openwrtgui.net.routes import RouteRequest
from openwrtgui.net.service import NetworkService
from openwrtgui.ports.compile import MirrorRequest
from openwrtgui.ports.parse import parse_swconfig_show
from openwrtgui.ports.service import PortsService
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import WifiService

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"
MOVED = "192.168.1.12"
ANSWER_WAIT_S = 75.0  # a rollback restores at 60 s after the apply; the network reload takes a few more
FREE_PORT, MONITOR_PORT, OWN_PORT = 2, 1, 3  # LAN2, LAN3 (no link) and LAN1 (the PC) on AP2's switch0

Content = list[tuple[str, tuple[tuple[str, str], ...]]]


def _by_content(text: str) -> Content:
    """A config's sections as (type, options): libuci names anonymous ones from their content."""
    shown = parse_uci_show(text)
    return sorted(
        (
            shown[name],
            tuple(sorted((k.rsplit(".", 1)[1], v) for k, v in shown.items() if k.startswith(name + "."))),
        )
        for name in (k for k in shown if k.count(".") == 1)
    )


@dataclass(frozen=True)
class Found:
    network: Content
    dhcp: Content
    radio_disabled: str
    ports: tuple[tuple[int, bool | None, bool, bool], ...]  # (port, enabled, mirror rx, mirror tx)
    monitor: int | None


async def _found(t: Transport) -> Found:
    switch = parse_swconfig_show("switch0", (await t.run("swconfig dev switch0 show")).stdout)
    return Found(
        network=_by_content((await t.run("uci -X show network")).stdout),
        dhcp=_by_content((await t.run("uci -X show dhcp")).stdout),
        radio_disabled=(await t.run("uci -q get wireless.radio0.disabled")).stdout.strip(),
        ports=tuple((p.num, p.enabled, p.mirror_rx, p.mirror_tx) for p in switch.ports),
        monitor=switch.mirror_monitor_port,
    )


@dataclass
class Window:
    net: NetworkService
    ports: PortsService
    routers: RouterStore
    connect: Callable[[str], Awaitable[SshTransport]]

    @property
    def host(self) -> str:
        rec = self.routers.get("ap2")
        assert rec is not None
        return rec.host


def _proven(result: NetApplyResult) -> None:
    failed = [f"{c.name}: {c.detail}" for c in result.checks if c.ok is not True]
    assert result.applied and result.verified, failed or result.error


async def _answering(connect: Callable[[str], Awaitable[SshTransport]], host: str) -> SshTransport | None:
    deadline = time.monotonic() + ANSWER_WAIT_S
    while True:
        try:
            return await connect(host)
        except TransportError:
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(3)


@pytest.fixture
async def window(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[Window]:
    found = await _found(ap2_rw)
    assert found.radio_disabled == "1", "AP2's radio must be parked before the window"
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    identity: Path = request.config.getoption("--identity")

    async def connect(host: str) -> SshTransport:
        return await SshTransport.connect(host, 22, "root", host_keys=host_keys, key_paths=[identity])

    async def factory(rec: RouterRecord) -> Transport:
        return await connect(rec.host)

    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    wifi = WifiService(
        pool=pool, routers=routers, guard=guard, audit=audit, descriptions=descriptions, statuses=statuses
    )
    common = {"pool": pool, "routers": routers, "guard": guard, "audit": audit, "descriptions": descriptions}
    net = NetworkService(**common, statuses=statuses, runner=runner, wifi=wifi)  # type: ignore[arg-type]
    ports = PortsService(**common, runner=runner)  # type: ignore[arg-type]
    w = Window(net, ports, routers, connect)
    try:
        yield w
    finally:
        await pool.close_all()
        t = await _answering(connect, AP2)
        if t is None and w.host == MOVED:  # stuck at .12 after a failed move back: move it back now
            _proven(await net.apply_interface("ap2", InterfaceRequest(name="lan", address=f"{AP2}/24")))
            await pool.close_all()
            t = await _answering(connect, AP2)
        assert t is not None, (
            f"AP2 does not answer at {AP2} {ANSWER_WAIT_S:g} s after the test: stop, tell Dmitry"
        )
        try:
            assert await _found(t) == found, "AP2 is not as found"
        finally:
            await t.close()


async def test_lan_address_change_follows_and_confirms(window: Window) -> None:
    started = time.monotonic()
    moved = await window.net.apply_interface("ap2", InterfaceRequest(name="lan", address=f"{MOVED}/24"))
    print(f"\nlan -> {MOVED}: {time.monotonic() - started:.1f} s, checks {[c.name for c in moved.checks]}")
    try:
        _proven(moved)
        assert window.host == MOVED and moved.host == MOVED
    finally:
        back = await window.net.apply_interface("ap2", InterfaceRequest(name="lan", address=f"{AP2}/24"))
    _proven(back)
    assert window.host == AP2


async def test_same_host_change_that_cuts_the_app_off_rolls_back(window: Window) -> None:
    """lan 192.168.1.2/30 leaves the PC (192.168.1.10) outside lan's subnet at the same address: the app
    must never confirm it, and the router must restore itself (final review, Important 1)."""
    started = time.monotonic()
    cut = await window.net.apply_interface("ap2", InterfaceRequest(name="lan", address=f"{AP2}/30"))
    print(f"\nlan /30: {time.monotonic() - started:.1f} s, {[(c.name, c.ok) for c in cut.checks]}")
    assert not cut.applied, cut
    assert {c.name: c.ok for c in cut.checks} == {"reconnected": False, "restored": True}, cut.checks
    assert window.host == AP2


async def test_unconfirmed_change_rolls_back(window: Window) -> None:
    started = time.monotonic()
    away = await window.net.apply_interface("ap2", InterfaceRequest(name="lan", address="192.168.77.2/24"))
    print(
        f"\nlan -> 192.168.77.2: {time.monotonic() - started:.1f} s, {[(c.name, c.ok) for c in away.checks]}"
    )
    assert not away.applied, away
    assert {c.name: c.ok for c in away.checks} == {"reconnected": False, "restored": True}, away.checks
    assert window.host == AP2


async def test_free_port_disable_and_enable_all(window: Window) -> None:
    state = await window.ports.state("ap2")
    lan2 = next(p for p in state.ports if p.num == FREE_PORT)
    assert not lan2.link and lan2.lock is None, "LAN2 must be free (no link, not the app's port)"
    assert next(p for p in state.ports if p.num == OWN_PORT).lock is not None
    try:
        _proven(await window.ports.apply_ports("ap2", FREE_PORT, False))
    finally:
        on = await window.ports.apply_ports("ap2", None, None, all_on=True)
    _proven(on)


async def test_mirror_on_free_ports_and_off(window: Window) -> None:
    try:
        on = await window.ports.apply_mirror(
            "ap2", MirrorRequest(monitor=MONITOR_PORT, sources={FREE_PORT: (True, True)})
        )
        _proven(on)
        mirror = (await window.ports.state("ap2")).mirror
        assert mirror.monitor == MONITOR_PORT and mirror.sources == {FREE_PORT: (True, True)}
    finally:
        off = await window.ports.apply_mirror("ap2", MirrorRequest(monitor=None, sources={}))
    _proven(off)


async def test_dns_change_is_saved_although_libuci_renames_the_section(window: Window) -> None:
    """dnsmasq's section on AP2 is anonymous, so libuci names it anew after the commit (final review,
    Important 2): the saved check must still find it."""
    dns = (await window.net.state("ap2")).dns
    assert dns is not None
    was = dns.values.get("cachesize")
    if was is None:
        pytest.skip("AP2 sets no cachesize: nothing to change and put back")
    changed = await window.net.apply_dns("ap2", DnsRequest(cachesize=int(was) + 7))
    try:
        _proven(changed)
    finally:
        back = await window.net.apply_dns("ap2", DnsRequest(cachesize=int(was)))
    _proven(back)


async def test_host_route_checked_as_ip_prints_it(window: Window) -> None:
    """`ip -j route` prints a /32 route without its prefix (final review, Important 3)."""
    route = RouteRequest(None, "route", "lan", "10.99.0.7/32", gateway="192.168.1.1")
    added = await window.net.apply_routes("ap2", [route], [], [], [])
    section = next(
        (r.section for r in (await window.net.state("ap2")).routes if r.target.startswith("10.99.0.7")), None
    )
    assert section is not None, f"the route was not saved: {added}"
    try:
        _proven(added)
    finally:
        gone = await window.net.apply_routes("ap2", [], [section], [], [])
    _proven(gone)
