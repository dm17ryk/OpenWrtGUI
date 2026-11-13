"""AP2 on air for the v0.7 test helpers (plan Task 17, HW-2): the step-through, owgmon0 across a reload, a
scan with `ap-force`, and with the bench phone the re-join advance and frame analysis on AP2's own BSS.

    uv run pytest -m hardware tests/hardware/test_ap2_on_air.py --router 192.168.1.2 --identity <key> \
        --known-hosts <file> --allow-writes --txctl-told [--adb-station <serial> --phone-app <package>] -v -s

Run it only in a window Dmitry OK'd at the time, with the parent session's "AP2 free, txctl told", Bench Guard
clear, never between 20:15 and 09:30, at most 30 minutes on air. Everything on air is channel 11 (txctl: AP1
stays on air on channel 1, AP3 parked). AP2 goes on air only as `OwgTest` with a key made for the run, so no
harness station joins; AP2's own SSID is never put on air (AP1 broadcasts it). Each test writes AP2's
/etc/config/wireless back as found, parks the radio and checks `uci -q show wireless`, the lab options and
that no owgmon0 or owgscan0 is left.

The phone (`--adb-station`) is the acoustic session's: it is read over adb before and after, and must end as
its owner left it (phone_state.py), their app (`--phone-app`) included. Without both the phone tests skip.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from phone_state import PhoneState, as_found_problems, read_phone, start_problems
from test_ap2_wifi_faults import (
    LAB,
    TEST_SSID,
    AdbStation,
    _Hidden,
    _on_air,
    _restore,
    _test_bss,
    _uci_wireless,
)

from conftest import FwWindow, wireless_snapshot
from openwrtgui.guard.writes import run_audited
from openwrtgui.rf.air import SCAN_IF
from openwrtgui.rf.frames_service import FrameAnalyzer
from openwrtgui.rf.scan_service import ScanService
from openwrtgui.transport.base import CommandResult, ubus_call
from openwrtgui.transport.ssh import SshTransport
from openwrtgui.wifi.model import ChannelSelection, ModeSelection, RadioRequest, SsidRequest, TxPowerSetting
from openwrtgui.wifi.monitor import INFO, MONITOR
from openwrtgui.wifi.parse import parse_iw_dev, parse_uci_show
from openwrtgui.wifi.step_service import ENDED, StepJob, StepService
from openwrtgui.wifi.steps import StepRequest

pytestmark = pytest.mark.hardware

AP2 = "ap2"
CHANNEL = 11  # txctl, 2026-11-12: HW-2 on channel 11 only
UP_WAIT_S = 30
RUN_LIMIT_S = 600
JOIN_WAIT_S = 240  # the first join may wait for the owner to unlock the phone and tap Allow
PHONE_SETTLE_S = 30
PING = "ping -c 75 -i 0.2 192.168.1.2"
RunFn = Callable[[str, bool], Awaitable[CommandResult]]


@dataclass
class AirWindow:
    w: FwWindow
    t: SshTransport
    key: str
    steps: StepService
    documents: Path


@pytest.fixture
async def air(fw_window: FwWindow, tmp_path: Path) -> AsyncIterator[AirWindow]:
    """AP2 as found before, and written back, parked and checked after, whatever the test did."""
    t = await fw_window.connect()
    snapshot = await wireless_snapshot(t)
    before = await _uci_wireless(t)
    steps = StepService(
        wifi=fw_window.wifi,
        pool=fw_window.pool,
        routers=fw_window.routers,
        guard=fw_window.guard,
        statuses={},
        steps_dir=tmp_path / "steps",
        documents=tmp_path / "Documents",
    )
    try:
        yield AirWindow(fw_window, t, _Hidden(secrets.token_urlsafe(16)), steps, tmp_path / "Documents")
    finally:
        try:
            await steps.stop_all(120)  # a run still going restores first
        finally:
            passes = await _restore(t, snapshot)
            if passes != 1:
                print(f"\nAP2's park took {passes or 'more than 2'} passes (O21)")
            after = await _uci_wireless(t)
            names = [i.ifname for i in parse_iw_dev((await t.run("iw dev")).stdout)]
            parked = not await _on_air(t)
            await t.close()
        if after != before:  # not an assert: pytest would print both, AP2's own key included
            pytest.fail("AP2's wireless config is not as found after the window")
        uci = parse_uci_show(after)
        assert {k: uci.get(k) for k in LAB} == LAB
        assert MONITOR not in names and SCAN_IF not in names, names
        assert parked, "radio0 is still on air after the restore"


@pytest.fixture
async def phone(request: pytest.FixtureRequest) -> AsyncIterator[tuple[AdbStation, PhoneState]]:
    """The bench phone, read before anything goes on air and checked after: as its owner left it."""
    serial = request.config.getoption("--adb-station")
    app = request.config.getoption("--phone-app")
    if not serial or not app:
        pytest.skip(
            "pass --adb-station <serial> and --phone-app <package> of the bench phone (its owner's OK)"
        )
    found = await read_phone(serial, app)
    if problems := start_problems(found, app):
        pytest.fail("the phone is not as its owner described it; ask before using it: " + "; ".join(problems))
    station = AdbStation(serial)
    try:
        yield station, found
    finally:
        with contextlib.suppress(RuntimeError):
            await station.forget(TEST_SSID)
        problems = []
        for _ in range(PHONE_SETTLE_S):  # Android takes a moment to drop a removed suggestion's network
            problems = as_found_problems(found, await read_phone(serial, app), app)
            if not problems:
                break
            await asyncio.sleep(1)
        assert problems == [], problems


def _audited(a: AirWindow) -> RunFn:
    async def run(command: str, require_guard: bool) -> CommandResult:
        return await run_audited(
            a.t,
            command,
            router_id=AP2,
            screen="Wi-Fi",
            guard=a.w.guard,
            audit=a.w.audit,
            source="user" if require_guard else "app",
            require_guard=require_guard,
        )

    return run


async def _owgtest_on_air(a: AirWindow) -> str:
    """OwgTest on channel 11 with the run's key; the AP interface that serves it."""
    on = await a.w.wifi.apply(
        AP2,
        RadioRequest(
            radio="radio0",
            modes=ModeSelection("set", frozenset({"n20"})),
            channels=ChannelSelection("set", frozenset({CHANNEL})),
            txpower=TxPowerSetting("auto"),
            ssids=(SsidRequest(section="default_radio0", ssid=TEST_SSID, key=a.key),),
        ),
    )
    assert on.applied and on.verified, [f"{c.name}: {c.detail}" for c in on.checks if not c.ok] or on.error
    return await _test_bss(a.t)


async def _section(a: AirWindow) -> dict[str, object]:
    answer = await ubus_call(a.t, "uci", "get", {"config": "wireless", "section": "radio0"})
    values = (answer or {}).get("values", {})
    return {k: v for k, v in values.items() if not k.startswith(".")}


async def _run(a: AirWindow, req: StepRequest) -> StepJob:
    plan = await a.steps.preview(AP2, req)
    print("\n" + "\n".join(line for lines in plan.step_lines for line in lines))
    await a.steps.start(AP2, req, plan.digest)
    for _ in range(RUN_LIMIT_S):
        job = a.steps.job(AP2)
        if job is not None and job.phase in ENDED:
            return job
        await asyncio.sleep(1)
    pytest.fail(f"the step-through did not end in {RUN_LIMIT_S} s")


def _print(job: StepJob) -> None:
    for r in job.results:
        print(
            f"step {r.index} {r.mode} ch{r.channel}: proven={r.proven} beacon={r.beacon} "
            f"rejoined={r.rejoined} rejoin_s={r.rejoin_s}"
        )
    print(f"phase={job.phase} error={job.error} csv={job.csv_path}")


async def test_step_through_on_air(air: AirWindow) -> None:
    """g and n20 on channel 11, a 20 s timer: both proven, beacons at 6.0 Mb/s, the CSV written, the radio
    back as the step-through found it (OwgTest on air), then parked by the fixture."""
    await _owgtest_on_air(air)
    found = await _section(air)
    job = await _run(air, StepRequest("radio0", ("g", "n20"), (CHANNEL,), advance="timer", dwell_s=20))
    _print(job)
    assert job.phase == "done" and job.error is None and not job.restore_pending
    assert [r.proven for r in job.results] == [True, True]
    assert all(r.beacon is not None and r.beacon.startswith("6.0 Mb/s") for r in job.results), job.results
    assert job.csv_path is not None and len(Path(job.csv_path).read_text().splitlines()) == 3
    assert await _section(air) == found


async def test_owgmon0_after_a_reload(air: AirWindow) -> None:
    """Hold the monitor, reload the radio, record whether owgmon0 survived (spec O21); `ensure` handles
    both."""
    await _owgtest_on_air(air)
    run = _audited(air)
    monitors = air.w.wifi.monitors
    await monitors.acquire(AP2, "HW-2", "phy0", air.t, run)
    try:
        assert (await air.t.run(INFO)).ok
        assert (await run("wifi down radio0; wifi up radio0", True)).ok
        for _ in range(UP_WAIT_S):
            if await _on_air(air.t):
                break
            await asyncio.sleep(1)
        survived = (await air.t.run(INFO)).ok
        print(f"\nowgmon0 survived a radio reload: {survived}")
        assert await monitors.ensure(AP2, "phy0", air.t, run) == (not survived)
        assert (await air.t.run(INFO)).ok
    finally:
        await monitors.release(AP2, "HW-2", run, air.t)
    assert not (await air.t.run(INFO)).ok


async def test_ap_scan(air: AirWindow) -> None:
    """A scan with `ap-force` while on air: networks and channel loads read, and whatever AP2 hears of its own
    BSSes is marked `own`. HW-2 (2026-11-13): 58 BSSes and none of them AP2's own, since a radio does not
    receive its own beacons; `own` marks what another radio of the same router hears (spec O21)."""
    await _owgtest_on_air(air)
    scans = ScanService(
        pool=air.w.pool, routers=air.w.routers, guard=air.w.guard, audit=air.w.audit, wifi=air.w.wifi
    )
    plan = await scans.preview(AP2, "radio0")
    assert plan.via == "ap", plan
    result = await scans.scan(AP2, "radio0", plan.digest)
    mine = {
        i.addr.lower() for i in parse_iw_dev((await air.t.run("iw dev")).stdout) if i.type == "AP" and i.addr
    }
    heard = [n for n in result.networks if n.bssid in mine]
    print(
        f"\nscan via {result.via}: {len(result.networks)} BSSes in {result.seconds:.1f} s; "
        f"own heard: {len(heard)}"
    )
    assert result.networks, "the scan heard no network"
    assert all(n.own for n in heard) and not any(n.own for n in result.networks if n.bssid not in mine)
    assert any(c.busy_pct is not None for c in result.channels)


async def _joined(a: AirWindow, station: AdbStation, bss: str) -> str:
    for second in range(JOIN_WAIT_S):
        clients = (await ubus_call(a.t, f"hostapd.{bss}", "get_clients") or {}).get("clients", {})
        joined = [k.lower() for k, v in clients.items() if isinstance(v, dict) and v.get("authorized")]
        if len(joined) == 1:
            return joined[0]
        assert len(joined) < 2, f"more than one station on {TEST_SSID}"
        if second % 10 == 0:
            await station.scan()
        await asyncio.sleep(1)
    pytest.fail(f"the phone did not join {TEST_SSID} in {JOIN_WAIT_S} s")


async def test_rejoin_advance(air: AirWindow, phone: tuple[AdbStation, PhoneState]) -> None:
    """g then n20 on channel 11, each step waits for the phone to re-join (limit 120 s): both re-joined."""
    station, _found = phone
    bss = await _owgtest_on_air(air)
    await station.join(TEST_SSID, air.key)
    print(f"\nwaiting up to {JOIN_WAIT_S} s for the phone: unlock it, tap Allow on the suggestions prompt")
    mac = await _joined(air, station, bss)
    req = StepRequest("radio0", ("g", "n20"), (CHANNEL,), advance="rejoin", station=mac, rejoin_limit_s=120)
    job = await _run(air, req)
    _print(job)
    assert job.phase == "done" and job.error is None
    assert [r.rejoined for r in job.results] == [True, True], [r.rejoin_s for r in job.results]


async def test_frame_analysis_own_bss(air: AirWindow, phone: tuple[AdbStation, PhoneState]) -> None:
    """The phone pings AP2 for 15 s; 3 frame windows read RX and TX frames and a rate mix. The phone's
    minstrel rc_stats are printed for spec O6."""
    station, _found = phone
    bss = await _owgtest_on_air(air)
    await station.join(TEST_SSID, air.key)
    mac = await _joined(air, station, bss)
    published: list[dict[str, object]] = []
    frames = FrameAnalyzer(
        AP2,
        "radio0",
        pool=air.w.pool,
        routers=air.w.routers,
        guard=air.w.guard,
        audit=air.w.audit,
        monitors=air.w.wifi.monitors,
        publish=published.append,
    )
    plan = await frames.preview()
    await frames.start(plan.digest)
    ping = asyncio.create_task(
        asyncio.to_thread(
            subprocess.run,
            ["adb", "-s", station.serial, "shell", PING],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    )
    try:
        for _ in range(60):
            if frames.state().windows >= 3:
                break
            await asyncio.sleep(1)
    finally:
        state = await frames.stop()
        done = await ping
    print(f"\nping: {(done.stdout.strip().splitlines() or [''])[-1]}")
    totals = state.totals
    assert state.windows >= 3 and totals is not None, state
    print(
        f"windows={state.windows} rx={totals.rx.frames} {totals.rx.rates} "
        f"tx={totals.tx.frames} {totals.tx.rates}"
    )
    assert totals.rx.frames > 0 and totals.tx.frames > 0
    assert len(totals.rx.rates) + len(totals.tx.rates) > 1  # a rate mix
    rc = await air.t.run(f"cat /sys/kernel/debug/ieee80211/phy0/netdev:{bss}/stations/{mac}/rc_stats")
    print("rc_stats (O6):\n" + (rc.stdout if rc.ok else f"not readable: {rc.stderr.strip()}"))
    assert str(air.key) not in repr(published)  # the run's key is never published
