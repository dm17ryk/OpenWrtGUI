"""AP2 window, 1.1b Part 3: LTE Recover proven on the real modem (LTE Recover plan Task 13, its spec 4.8).

    uv run pytest -m hardware tests/hardware/test_ap2_lte_recover.py --router 192.168.1.2 --identity <key> \
        --known-hosts <file> --allow-writes --txctl-told -v -s

Run it only in a window Dmitry OK'd at the time, Bench Guard clear, the txctl session told: AP2's LTE drops
several times (about 15 minutes). Nothing here breaks the modem on purpose: never `AT&F`, never the QMI reset
mode. The `lte` fixture (test_ap2_lte.py) leaves AP2 as found, LTE up again. If the modem ends in any state
but working, the test fails: stop and tell Dmitry.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

import pytest
from test_ap2_lte import POLL_S, UP_WAIT_S, _lte_up, lte  # noqa: F401 - lte is the window's fixture
from test_ap2_wifi import _recorder

from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.lte import commands as c
from openwrtgui.lte.recover import RECOVERED, RUNGS, WORKS, LteRecover, LteRecoverJob
from openwrtgui.lte.service import LteService
from openwrtgui.lte.setups import SetupStore
from openwrtgui.net.apply import NOTHING
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.transport.ssh import SshTransport

pytestmark = pytest.mark.hardware

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ap2" / "lte_recover.json"


def _recover(service: LteService, tmp_path: Path) -> LteRecover:
    routers = RouterStore(tmp_path / "recover-routers.json")
    routers.upsert(
        RouterRecord(id="ap2", name="AP2", host="192.168.1.2", auth="key", added_at=datetime.now())
    )
    guard = BenchGuard(GuardWatchList())
    guard.check_local()
    return LteRecover(lte=service, setups=SetupStore(tmp_path / "lte-setups"), routers=routers, guard=guard)


def _not_settled_for(recover: LteRecover, rungs: int) -> None:
    """The LTE plan's test hook (Task 13 Step 4): the first `rungs` rungs do not count as settled, so Recover
    climbs to the next one and that one runs on the real modem. Each still waits for LTE first, as real
    Recover does (2026-11-19 window: skipping the wait cut netifd's connect script off mid-setup, and LTE
    stayed down until a router reboot)."""
    real: Callable[..., Awaitable[bool]] = recover._wait_works  # noqa: SLF001
    real_works: Callable[..., Awaitable[bool]] = recover._works  # noqa: SLF001
    calls = 0

    async def wait(run: object) -> bool:
        nonlocal calls
        calls += 1
        works = await real(run)
        return works and calls > rungs

    async def works_before_step(run: object) -> bool:
        """v1.3a I2: Recover also checks LTE before each step; a forced step is not settled there either."""
        return calls > rungs and await real_works(run)

    recover._wait_works = wait  # type: ignore[method-assign] # noqa: SLF001
    recover._works = works_before_step  # type: ignore[method-assign] # noqa: SLF001


async def _run(recover: LteRecover) -> LteRecoverJob:
    await recover.start("ap2", (await recover.preview("ap2")).digest)
    job = await recover.finished("ap2")
    assert job is not None
    print(f"\n{job.phase}: {job.detail} {[(r.name, r.outcome, r.detail) for r in job.rungs]}")
    return job


async def _disconnect(service: LteService) -> None:
    plan = await service.plan_action("ap2", "disconnect")
    down = await service.apply_action("ap2", "disconnect", plan.digest)
    assert (down.applied, down.verified) == (True, True), down


async def test_recover_on_ap2(lte: LteService, ap2_rw: SshTransport, tmp_path: Path) -> None:  # noqa: F811
    device = await lte.lte_device("ap2")
    assert device is not None, "AP2's network.lte.device names no QMI device"
    rf = _recorder()
    # Step 1: --sync between ifdown and ifup, recorded as the modem answers it, then lte's status (pdh_4)
    recorded = await rf.run_set(
        ap2_rw, (c.IFDOWN_LTE, c.sync(device), c.IFUP_LTE), timed=frozenset({c.sync(device)})
    )
    for _ in range(int(UP_WAIT_S / POLL_S)):
        if await _lte_up(ap2_rw) is True:
            break
        await asyncio.sleep(POLL_S)
    recorded |= await rf.run_set(ap2_rw, (c.iface_status("lte"),))
    FIXTURE.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nrecorded {len(recorded)} commands to {FIXTURE}")
    assert recorded[c.sync(device)]["exit"] == 0, recorded[c.sync(device)]
    # Step 2: on a working modem there is nothing to do
    job = await _run(_recover(lte, tmp_path))
    assert (job.phase, job.detail) == ("works", WORKS)
    # Step 3: after a disconnect, Reconnect brings it back
    await _disconnect(lte)
    job = await _run(_recover(lte, tmp_path))
    assert (job.phase, job.detail) == ("recovered", RECOVERED.format(rung=RUNGS[1]))
    # Step 4: rungs 3, 4 and 5 once each (the earlier ones do not count as settled)
    for index in (2, 3, 4):
        await _disconnect(lte)
        recover = _recover(lte, tmp_path)
        _not_settled_for(recover, index - 1)
        job = await _run(recover)
        assert (job.phase, job.detail) == ("recovered", RECOVERED.format(rung=RUNGS[index])), job
    # Step 5: Save good setup, then Reconfigure from it changes nothing
    setups = SetupStore(tmp_path / "lte-setups")
    await lte.save_setup("ap2", setups)
    with pytest.raises(ValueError, match=NOTHING):
        await lte.plan_setup("ap2", "ap2", setups)
    assert await _lte_up(ap2_rw) is True, "LTE is not up at the end: stop and tell Dmitry"
