"""AP2 LTE window (v0.6a plan Task 16): connect, disconnect, the safe modem reboot, one settings change and
back, and an AT query, applied the way the app applies them, on the real router.

uv run pytest -m hardware tests/hardware/test_ap2_lte.py --router 192.168.1.2 --identity <key> \
    --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window the owner approved and the txctl session was told of: AP2's LTE session drops several
times (about 5 minutes in all). The modem is never set to `reset`. Each test leaves AP2 as it found it; the
fixture waits for lte to be up again and checks `uci -X show network` and lte's up state as found.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.lte import commands as c
from openwrtgui.lte.service import LteService
from openwrtgui.lte.settings import LteSettings
from openwrtgui.net.apply import ApplyRunner
from openwrtgui.net.service import NetworkService
from openwrtgui.probe.describe import SelfDescription
from openwrtgui.probe.status import RouterStatus
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.base import Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import WifiService

pytestmark = pytest.mark.hardware

AP2 = "192.168.1.2"
UP_WAIT_S = 120.0  # lte comes back within about a minute after a disconnect or a modem reboot
POLL_S = 3.0


def _by_content(text: str) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    shown = parse_uci_show(text)
    return sorted(
        (
            shown[name],
            tuple(sorted((k.rsplit(".", 1)[1], v) for k, v in shown.items() if k.startswith(name + "."))),
        )
        for name in (k for k in shown if k.count(".") == 1)
    )


async def _lte_up(t: Transport) -> bool | None:
    result = await t.run(c.iface_status("lte"))
    try:
        return bool(json.loads(result.stdout).get("up")) if result.ok else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Found:
    network: list[tuple[str, tuple[tuple[str, str], ...]]]
    lte_up: bool | None


async def _found(t: Transport) -> Found:
    return Found(_by_content((await t.run("uci -X show network")).stdout), await _lte_up(t))


@pytest.fixture
async def lte(
    ap2_rw: SshTransport, request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[LteService]:
    found = await _found(ap2_rw)
    assert found.lte_up is not None, "lte's status does not read on AP2"
    host_keys = HostKeyStore(tmp_path / "known_hosts")
    shutil.copyfile(request.config.getoption("--known-hosts"), host_keys.path)
    identity: Path = request.config.getoption("--identity")

    async def factory(rec: RouterRecord) -> Transport:
        return await SshTransport.connect(AP2, 22, "root", host_keys=host_keys, key_paths=[identity])

    routers = RouterStore(tmp_path / "routers.json")
    routers.upsert(RouterRecord(id="ap2", name="AP2", host=AP2, auth="key", added_at=datetime.now()))
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    pool = ConnectionPool(factory)
    audit = AuditLog(tmp_path / "audit")
    descriptions: dict[str, SelfDescription] = {}
    statuses: dict[str, RouterStatus] = {}
    runner = ApplyRunner(pool=pool, routers=routers, guard=guard, audit=audit, host_keys=host_keys)
    common = {"pool": pool, "routers": routers, "guard": guard, "audit": audit, "descriptions": descriptions}
    wifi = WifiService(**common, statuses=statuses)  # type: ignore[arg-type]
    net = NetworkService(**common, statuses=statuses, runner=runner, wifi=wifi)  # type: ignore[arg-type]
    service = LteService(pool=pool, routers=routers, guard=guard, audit=audit, net=net)
    try:
        yield service
    finally:
        await pool.close_all()
        t = await factory(routers.get("ap2"))  # type: ignore[arg-type]
        try:
            for _ in range(int(UP_WAIT_S / POLL_S)):  # lte up again before the as-found check
                if not found.lte_up or await _lte_up(t) is True:
                    break
                await asyncio.sleep(POLL_S)
            assert await _found(t) == found, "AP2 is not as found"
        finally:
            await t.close()


async def test_disconnect_then_connect(lte: LteService) -> None:
    started = time.monotonic()
    plan = await lte.plan_action("ap2", "disconnect")
    down = await lte.apply_action("ap2", "disconnect", plan.digest)
    print(f"\ndisconnect: {time.monotonic() - started:.1f} s, {down.checks}")
    assert (down.applied, down.verified) == (True, True), down
    started = time.monotonic()
    plan = await lte.plan_action("ap2", "connect")
    up = await lte.apply_action("ap2", "connect", plan.digest)
    print(f"connect: {time.monotonic() - started:.1f} s, {up.checks}")
    assert (up.applied, up.verified) == (True, True), up


async def test_reboot_modem(lte: LteService) -> None:
    started = time.monotonic()
    plan = await lte.plan_action("ap2", "reboot")
    assert not any("reset" in line for line in plan.lines)
    result = await lte.apply_action("ap2", "reboot", plan.digest)
    print(f"\nreboot modem: {time.monotonic() - started:.1f} s, {result.checks}")
    assert (result.applied, result.verified) == (True, True), result
    names = {check.name: check.ok for check in result.checks}
    assert names["modem low_power"] and names["modem online"] and names["lte up"]


async def test_a_metric_change_and_back(lte: LteService) -> None:
    rows = {r.name: r for r in await lte.settings_options("ap2")}
    current = int(str(rows["metric"].value or "0"))
    for metric in (current + 1, current):
        plan = await lte.plan_settings("ap2", LteSettings(metric=metric))
        assert any(line.endswith(f"network.lte.metric='{metric}'") for line in plan.lines), plan.lines
        started = time.monotonic()
        result = await lte.apply_settings("ap2", LteSettings(metric=metric), plan.digest)
        print(f"\nmetric {metric}: {time.monotonic() - started:.1f} s, {result.checks}")
        assert (result.applied, result.verified) == (True, True), result


async def test_an_at_query_through_the_console(lte: LteService) -> None:
    result = await lte.at_command("ap2", "AT+CSQ", confirmed=False)
    print(f"\nAT+CSQ: {result}")
    assert result.status == "OK" and any(line.startswith("+CSQ:") for line in result.lines)
