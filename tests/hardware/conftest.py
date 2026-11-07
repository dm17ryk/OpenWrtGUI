"""Fixtures for `pytest -m hardware`: an SSH connection to AP2 (192.168.1.2), nothing else.

uv run pytest -m hardware --router 192.168.1.2 --identity C:/Essence_SC/home/.ssh/id_rsa -v

`ap2` only reads. `ap2_luci` also makes the LuCI bridge's in-memory rpcd sessions and its SSH forward.
`ap2_rw` changes AP2 (and the test restores it); it runs only with --allow-writes --txctl-told:

uv run pytest -m hardware tests/hardware/test_ap2_wifi.py --router 192.168.1.2 --identity <key> \
    --allow-writes --txctl-told -v
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from ro_transport import LuciSessionTransport, ReadOnlyTransport, write_refusal

from openwrtgui.capture.service import CaptureService
from openwrtgui.faults.service import FaultsService
from openwrtgui.fw.service import FirewallService
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.net.service import NetworkService
from openwrtgui.ports.parse import parse_swconfig_show
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList, SettingsStore
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import WifiService

AP2 = "192.168.1.2"


async def _connect(request: pytest.FixtureRequest) -> SshTransport:
    router: str = request.config.getoption("--router")
    identity: Path | None = request.config.getoption("--identity")
    if router != AP2 and not request.config.getoption("--allow-other"):
        pytest.fail(f"hardware tests run on AP2 ({AP2}) only; --allow-other to use {router}", pytrace=False)
    if identity is None:
        pytest.skip("pass --identity <private key> that the router accepts")
    state = BenchGuard(GuardWatchList()).check_local()
    if state.live:
        pytest.skip("Bench Guard sees a run: " + "; ".join(r.text for r in state.reasons))
    # The router's key must already be in known_hosts (checked by the user); never pinned here.
    host_keys = HostKeyStore(request.config.getoption("--known-hosts"))
    return await SshTransport.connect(router, 22, "root", host_keys=host_keys, key_paths=[identity])


@pytest.fixture
async def ap2(request: pytest.FixtureRequest) -> AsyncIterator[ReadOnlyTransport]:
    transport = await _connect(request)
    try:
        yield ReadOnlyTransport(transport)
    finally:
        await transport.close()


@pytest.fixture
async def ap2_luci(request: pytest.FixtureRequest) -> AsyncIterator[LuciSessionTransport]:
    transport = await _connect(request)
    try:
        yield LuciSessionTransport(transport)
    finally:
        await transport.close()


@dataclass
class FwWindow:
    """The app's firewall, faults and capture services on AP2, as the app builds them (context.py)."""

    fw: FirewallService
    faults: FaultsService
    captures: CaptureService
    net: NetworkService
    connect: Callable[[], Awaitable[SshTransport]]
    pool: ConnectionPool


def _by_content(text: str) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    """A config's sections as (type, options): libuci names anonymous ones from their content."""
    shown = parse_uci_show(text)
    return sorted(
        (
            shown[name],
            tuple(sorted((k.rsplit(".", 1)[1], v) for k, v in shown.items() if k.startswith(name + "."))),
        )
        for name in (k for k in shown if k.count(".") == 1)
    )


async def fw_found(t: Transport) -> dict[str, object]:
    """What the firewall and faults window must leave as it found: firewall config, nft tables, qdiscs,
    /tmp/owg, the switch ports, the parked radio."""
    switch = parse_swconfig_show("switch0", (await t.run("swconfig dev switch0 show")).stdout)
    return {
        "firewall": _by_content((await t.run("uci -X show firewall")).stdout),
        "tables": sorted((await t.run("nft list tables")).stdout.split("\n")),
        "qdiscs": (await t.run("tc qdisc show")).stdout,
        "owg": (await t.run("ls -A /tmp/owg 2>/dev/null")).stdout,
        "ports": [(p.num, p.enabled) for p in switch.ports],
        "radio": (await t.run("uci -q get wireless.radio0.disabled")).stdout.strip(),
    }


@pytest.fixture
async def fw_window(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[FwWindow]:
    found = await fw_found(ap2_rw)
    assert found["radio"] == "1", "AP2's radio must be parked before the window"
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    identity: Path = request.config.getoption("--identity")

    async def connect() -> SshTransport:
        return await SshTransport.connect(AP2, 22, "root", host_keys=host_keys, key_paths=[identity])

    async def factory(rec: RouterRecord) -> Transport:
        return await connect()

    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    settings = SettingsStore(tmp_path / "settings.json")
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    common = {"pool": pool, "routers": routers, "guard": guard, "audit": audit, "descriptions": descriptions}
    wifi = WifiService(**common, statuses=statuses)  # type: ignore[arg-type]
    net = NetworkService(**common, statuses=statuses, runner=runner, wifi=wifi)  # type: ignore[arg-type]
    w = FwWindow(
        fw=FirewallService(**common, settings=settings, runner=runner),  # type: ignore[arg-type]
        faults=FaultsService(**common, settings=settings, runner=runner),  # type: ignore[arg-type]
        captures=CaptureService(
            pool=pool,
            routers=routers,
            guard=guard,
            audit=audit,
            net=net,
            documents=tmp_path / "Documents",
            wireshark=lambda: None,
        ),
        net=net,
        connect=connect,
        pool=pool,
    )
    try:
        yield w
    finally:
        try:  # whatever a failed test left armed, and the app's empty benchfault table
            plan = await w.faults.plan_clear("ap2", None)
            await w.faults.apply_clear("ap2", None, plan.digest)
        except ValueError:
            pass  # nothing armed and no table
        await pool.close_all()
        t = await connect()
        try:
            assert await fw_found(t) == found, "AP2 is not as found"
        finally:
            await t.close()


@pytest.fixture
async def ap2_rw(request: pytest.FixtureRequest) -> AsyncIterator[SshTransport]:
    refusal = write_refusal(
        request.config.getoption("--router"),
        allow_writes=request.config.getoption("--allow-writes"),
        txctl_told=request.config.getoption("--txctl-told"),
    )
    if refusal:
        pytest.skip(refusal)
    transport = await _connect(request)
    try:
        yield transport
    finally:
        await transport.close()
