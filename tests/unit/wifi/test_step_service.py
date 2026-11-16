"""The step-through runner (v0.7 plan Task 11, D2-D10) on the simulator's AP2 (parked).

AP2's SSID is AP1's too: the runs here know no other router's status, except the on-air refusal test."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import WifiEnv
from openwrtgui.guard.bench_guard import GuardLocked
from openwrtgui.transport.base import CommandResult, Transport, TransportError
from openwrtgui.wifi.service import PreviewChanged
from openwrtgui.wifi.step_service import PendingRestore, StepBusy, StepJob, StepService
from openwrtgui.wifi.steps import SAVED_OPTIONS, StepRequest

DONE = ("done", "stopped", "failed")
TWO_BY_TWO = StepRequest("radio0", ("b", "g"), (1, 6), dwell_s=10)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> datetime:
        return datetime(2026, 11, 12, 10, 0) + timedelta(seconds=self.t)


class _Scripted:
    """A transport that changes chosen answers: rule(command, n-th time) -> result or None."""

    def __init__(self, inner: Transport, rule: Callable[[str, int], CommandResult | None]) -> None:
        self._inner = inner
        self._rule = rule
        self._seen: dict[str, int] = {}

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if "get_clients" in command:
            key = "get_clients"
        elif command.startswith("set -e"):
            key = "script"
        else:
            key = command.split(" ")[0]
        self._seen[key] = self._seen.get(key, 0) + 1
        changed = self._rule(command, self._seen[key])
        return changed if changed is not None else await self._inner.run(command, timeout=timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _Yielding:
    """Every command is an SSH round trip: other tasks run meanwhile."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        await asyncio.sleep(0)
        return await self._inner.run(command, timeout=timeout)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _service(
    env: WifiEnv, tmp_path: Path, clock: _Clock, statuses: dict[str, Any] | None = None, **kw: Any
) -> StepService:
    async def sleep(seconds: float) -> None:
        clock.t += seconds
        await asyncio.sleep(0)

    return StepService(
        wifi=env.service,
        pool=env.pool,
        routers=env.routers,
        guard=env.guard,
        statuses=statuses if statuses is not None else {},
        steps_dir=tmp_path / "steps",
        documents=tmp_path / "Documents",
        clock=clock.now,
        sleep=sleep,
        **kw,
    )


async def _until(check: Callable[[], bool]) -> None:
    for _ in range(5000):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError("did not happen")


async def _run(steps: StepService, router_id: str, req: StepRequest) -> StepJob:
    plan = await steps.preview(router_id, req)
    return await steps.start(router_id, req, plan.digest)


def _job(steps: StepService, router_id: str = "ap2") -> StepJob:
    job = steps.job(router_id)
    assert job is not None
    return job


def _phase(steps: StepService | None, router_id: str = "ap2") -> str | None:
    """The job's phase, or None before Start has made the job (a scripted rule runs during Start's reads)."""
    job = steps.job(router_id) if steps is not None else None
    return job.phase if job is not None else None


async def _parked(env: WifiEnv, router_id: str = "ap2") -> bool:
    status = json.loads((await (await env.sim(router_id)).run("ubus call network.wireless status")).stdout)
    return status["radio0"]["up"] is False


async def test_timer_run_proves_each_step_and_restores(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    plan = await steps.preview("ap2", TWO_BY_TWO)
    assert [(s.mode, s.channel) for s in plan.steps] == [("b", 1), ("b", 6), ("g", 1), ("g", 6)]
    assert "uci set wireless.radio0.disabled='1'" in plan.restore_lines
    assert plan.estimate_s == 4 * (20 + 10)
    await steps.start("ap2", TWO_BY_TWO, plan.digest)
    assert (tmp_path / "steps" / "ap2-radio0.json").exists()
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "done" and job.error is None and not job.restore_pending
    assert [r.proven for r in job.results] == [True] * 4
    assert job.results[0].beacon is not None and job.results[0].beacon.startswith("1.0 Mb/s")
    assert job.csv_path is not None and len(Path(job.csv_path).read_text().splitlines()) == 5
    assert Path(job.csv_path).parent == tmp_path / "Documents" / "OpenWrtGUI"
    assert not (tmp_path / "steps" / "ap2-radio0.json").exists()
    assert await _parked(env)
    screens = {e.screen for e in env.audit.query()}
    assert screens == {"Wi-Fi"}


async def test_list_options_end_as_found(env: WifiEnv, tmp_path: Path) -> None:
    """Re-graded review minor (D6): a radio whose rates are uci lists reads exactly as found after a run."""
    sim = await env.sim("ap2")
    for rate in ("6000", "12000", "24000"):
        assert (await sim.run(f"uci add_list wireless.radio0.basic_rate='{rate}'")).ok
    for rate in ("6000", "9000", "12000", "18000", "24000", "36000", "48000", "54000"):
        assert (await sim.run(f"uci add_list wireless.radio0.supported_rates='{rate}'")).ok
    assert (await sim.run("uci commit wireless")).ok
    found = (await sim.run("uci -q show wireless")).stdout
    assert "wireless.radio0.basic_rate='6000' '12000' '24000'" in found
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase in DONE)
    assert _job(steps).phase == "done", _job(steps).error
    assert (await sim.run("uci -q show wireless")).stdout == found


async def test_a_rejoin_estimate_is_the_worst_case(env: WifiEnv, tmp_path: Path) -> None:
    """PR #59 review: a re-join step can wait its whole limit and then dwell; the estimate counts both."""
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest(
        "radio0",
        ("g",),
        (1, 6),
        advance="rejoin",
        station="f4:12:fa:f3:57:68",
        dwell_s=60,
        rejoin_limit_s=120,
    )
    plan = await steps.preview("ap2", req)
    assert plan.estimate_s == 2 * (20 + 120 + 60)


async def test_manual_waits_for_next(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", StepRequest("radio0", ("g",), (1, 6), advance="manual"))
    await _until(lambda: _job(steps).phase == "waiting for Next")
    assert _job(steps).index == 1
    steps.next("ap2")
    await _until(lambda: _job(steps).phase == "waiting for Next" and _job(steps).index == 2)
    steps.next("ap2")
    await _until(lambda: _job(steps).phase in DONE)
    assert _job(steps).phase == "done" and len(_job(steps).results) == 2
    with pytest.raises(ValueError, match="Nothing waits for Next"):
        steps.next("ap2")


async def test_rejoin_records_the_time(env: WifiEnv, tmp_path: Path) -> None:
    def late(command: str, n: int) -> CommandResult | None:
        if "get_clients" in command and n <= 2:  # the station is back on the third read
            return CommandResult(command, '{"freq": 2412, "clients": {}}', "", 0)
        return None

    env.wrap.append(lambda t: _Scripted(t, late))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="F4:12:FA:F3:57:68", dwell_s=10)
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    [result] = _job(steps).results
    assert result.rejoined is True and result.rejoin_s == 2.0


async def test_a_starting_step_through_holds_the_router(env: WifiEnv, tmp_path: Path) -> None:
    """Review I6: from the moment Start passes its checks, a System job, a flash or a second Start on the
    router is refused, also while Start still reads the router."""
    env.wrap.append(lambda t: _Yielding(t))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest("radio0", ("g",), (1,), advance="manual")
    plan = await steps.preview("ap2", req)
    starting = asyncio.ensure_future(steps.start("ap2", req, plan.digest))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not starting.done()
    assert steps.busy("ap2") is not None
    with pytest.raises(StepBusy):
        await steps.start("ap2", req, plan.digest)
    await starting
    await steps.stop("ap2")
    await _until(lambda: _job(steps).phase in DONE)
    with pytest.raises(PreviewChanged):  # a Start that fails lets go of the router
        await steps.start("ap2", req, "0" * 16)
    assert steps.busy("ap2") is None


async def test_a_running_step_through_is_not_a_pending_restore(env: WifiEnv, tmp_path: Path) -> None:
    """Review I5: the saved options of a run in progress are its own, not a restore left behind."""
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", StepRequest("radio0", ("g",), (1, 6), advance="manual"))
    await _until(lambda: _job(steps).phase == "waiting for Next")
    assert (tmp_path / "steps" / "ap2-radio0.json").exists() and steps.pending() == []
    await steps.stop("ap2")
    await _until(lambda: _job(steps).phase in DONE)
    assert steps.pending() == []


async def test_rejoin_time_counts_from_the_reload(env: WifiEnv, tmp_path: Path) -> None:
    """Review I8: the reload drops the station; its re-join time counts from the step's start, not from the
    end of the Apply's checks (12 s of reload and proof here)."""
    clock = _Clock()

    def slow_reload(command: str, n: int) -> CommandResult | None:
        if command.startswith("set -e") and n == 1:
            clock.t += 12  # the step's Apply: reload, then the checks
        if "get_clients" in command and n <= 2:
            return CommandResult(command, '{"freq": 2412, "clients": {}}', "", 0)
        return None

    env.wrap.append(lambda t: _Scripted(t, slow_reload))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, clock)
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="F4:12:FA:F3:57:68", dwell_s=10)
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    [result] = _job(steps).results
    assert result.rejoined is True and result.rejoin_s == 14.0


async def test_rejoin_seen_on_any_ssid_of_the_radio(env: WifiEnv, tmp_path: Path) -> None:
    """PR #59 review: on a radio with two SSIDs the station may re-join the second one; every AP interface
    of the radio is read, not only the first."""
    sim = await env.sim("ap2")
    for line in (
        "uci set wireless.owg2=wifi-iface",
        "uci set wireless.owg2.device=radio0",
        "uci set wireless.owg2.mode=ap",
        "uci set wireless.owg2.network=lan",
        "uci set wireless.owg2.ssid=OwgSecond",
        "uci commit wireless",
    ):
        assert (await sim.run(line)).ok, line

    def first_is_empty(command: str, n: int) -> CommandResult | None:
        if "get_clients" in command and "hostapd.phy0-ap0 " in command:
            return CommandResult(command, '{"freq": 2412, "clients": {}}', "", 0)
        return None

    env.wrap.append(lambda t: _Scripted(t, first_is_empty))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="F4:12:FA:F3:57:68", dwell_s=10)
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    [result] = _job(steps).results
    assert result.rejoined is True, _job(steps)


async def test_rejoin_limit_records_not_rejoined_and_goes_on(env: WifiEnv, tmp_path: Path) -> None:
    def never(command: str, n: int) -> CommandResult | None:
        if "get_clients" in command:
            return CommandResult(command, '{"freq": 2412, "clients": {}}', "", 0)
        return None

    env.wrap.append(lambda t: _Scripted(t, never))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest(
        "radio0", ("g",), (1, 6), advance="rejoin", station="f4:12:fa:f3:57:68", rejoin_limit_s=30
    )
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "done" and [r.rejoined for r in job.results] == [False, False]


async def test_unproven_step_is_recorded_and_skipped(env: WifiEnv, tmp_path: Path) -> None:
    def deaf(command: str, n: int) -> CommandResult | None:
        if command.startswith("timeout 5 tcpdump") and n == 2:  # step 2 hears no beacon
            return CommandResult(command, "", "0 packets captured\n", 124)
        return None

    env.wrap.append(lambda t: _Scripted(t, deaf))  # type: ignore[arg-type,return-value]
    clock = _Clock()
    steps = _service(env, tmp_path, clock)
    await _run(steps, "ap2", StepRequest("radio0", ("g",), (1, 6, 11), dwell_s=10))
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert [r.proven for r in job.results] == [True, False, True] and job.phase == "done"
    failed = [c for c in job.results[1].checks if c.ok is False]
    assert [c.name for c in failed] == ["beacon rate"]
    assert job.results[1].ended_at == job.results[1].started_at  # no dwell for it


async def test_refused_change_stops_and_restores(env: WifiEnv, tmp_path: Path) -> None:
    def refuse(command: str, n: int) -> CommandResult | None:
        if command.startswith("set -e") and n == 2:
            return CommandResult(command, "", "uci: Invalid argument", 1)
        return None

    env.wrap.append(lambda t: _Scripted(t, refuse))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "failed" and job.error is not None and "refused the change" in job.error
    assert not job.restore_pending and await _parked(env)


async def test_stop_in_a_dwell_restores(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase == "dwell")
    await steps.stop("ap2")
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "stopped" and len(job.results) == 1 and not job.restore_pending
    assert await _parked(env) and not (tmp_path / "steps" / "ap2-radio0.json").exists()


async def test_stop_during_an_apply_restores_after_it(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    original = env.service.apply

    async def apply_then_stop(*args: Any, **kw: Any) -> Any:
        if _job(steps).index == 2:
            await steps.stop("ap2")  # pressed while step 2's change runs
        return await original(*args, **kw)

    env.service.apply = apply_then_stop  # type: ignore[method-assign]
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "stopped" and len(job.results) == 2 and await _parked(env)


async def test_guard_live_stops_without_restore(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase == "dwell")
    writes = len(env.audit_lines())
    env.go_live()
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "stopped" and job.restore_pending
    assert job.error is not None and "dima_night.py" in job.error
    assert len(env.audit_lines()) == writes  # nothing written once the run went live
    assert (tmp_path / "steps" / "ap2-radio0.json").exists()
    assert not await _parked(env)  # left at the step until Restore


async def test_the_guard_stop_names_the_step_the_radio_is_at(
    env: WifiEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.7 minor (#43), v1.0c Task 12: the run went live as step 2 began, so step 2 never changed the radio;
    the message names step 1, not the step that was about to start."""
    steps = _service(env, tmp_path, _Clock())
    update = steps._update

    def going_live(router_id: str, **kw: object) -> None:
        update(router_id, **kw)  # type: ignore[arg-type]
        if kw.get("phase") == "applying" and kw.get("index") == 2:
            env.go_live()  # a harness run starts just as step 2 begins

    monkeypatch.setattr(steps, "_update", going_live)
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.error is not None and "radio0 is left at step 1;" in job.error


async def test_restore_pending_after_guard_clears(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase == "dwell")
    env.go_live()
    await _until(lambda: _job(steps).phase in DONE)
    assert [p.radio for p in steps.pending()] == ["radio0"]
    with pytest.raises(GuardLocked):
        await steps.restore("ap2", "radio0")
    env.processes.clear()
    env.guard.check_local()
    result = await steps.restore("ap2", "radio0")
    assert result.verified and await _parked(env) and steps.pending() == []
    assert not _job(steps).restore_pending


async def test_changed_during_the_run_stops(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", TWO_BY_TWO)
    await _until(lambda: _job(steps).phase == "dwell")
    t = await env.sim("ap2")
    assert (await t.run("uci set wireless.radio0.htmode='HT20'\nuci commit wireless")).ok
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "failed" and job.error is not None and "changed during the step-through" in job.error
    assert await _parked(env)


async def test_start_refusals(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock(), busy=(lambda r: "AP2 is rebooting" if r == "ap2" else None,))
    plan = await steps.preview("ap2", TWO_BY_TWO)
    with pytest.raises(StepBusy, match="^AP2 is rebooting$"):
        await steps.start("ap2", TWO_BY_TWO, plan.digest)
    steps = _service(env, tmp_path, _Clock())
    with pytest.raises(PreviewChanged):
        await steps.start("ap2", TWO_BY_TWO, "0" * 16)
    on_air = _service(env, tmp_path, _Clock(), statuses=env.statuses)  # AP1 is on air with "OpenWrt"
    plan2 = await on_air.preview("ap2", TWO_BY_TWO)
    assert any("already on air" in w for w in plan2.warnings)
    with pytest.raises(ValueError, match="already on air"):
        await on_air.start("ap2", TWO_BY_TWO, plan2.digest)
    await steps.start("ap2", TWO_BY_TWO, plan.digest)
    with pytest.raises(StepBusy, match="^A step-through runs on "):
        await steps.start("ap2", TWO_BY_TWO, plan.digest)
    await steps.stop("ap2")
    await _until(lambda: _job(steps).phase in DONE)
    env.go_live()
    with pytest.raises(GuardLocked):
        await steps.start("ap2", TWO_BY_TWO, plan.digest)


async def test_pending_restore_blocks_a_new_start(env: WifiEnv, tmp_path: Path) -> None:
    folder = tmp_path / "steps"
    folder.mkdir()
    saved = {"router_id": "ap2", "radio": "radio0", "saved_at": "2026-11-12T09:00:00", "options": {}}
    (folder / "ap2-radio0.json").write_text(json.dumps(saved), encoding="utf-8")
    steps = _service(env, tmp_path, _Clock())
    plan = await steps.preview("ap2", TWO_BY_TWO)
    with pytest.raises(StepBusy, match="^Restore radio0 on .* first"):
        await steps.start("ap2", TWO_BY_TWO, plan.digest)


async def test_an_error_in_the_restore_never_leaves_the_run_restoring(env: WifiEnv, tmp_path: Path) -> None:
    """Review Focus 1, v0.7 minor: the job ends failed with Restore offered, and the router is free again."""
    steps: StepService | None = None

    def broken_restore(command: str, n: int) -> CommandResult | None:
        restoring = _phase(steps) == "restoring"
        if restoring and command.startswith("ubus call uci get"):
            raise RuntimeError("boom")
        return None

    env.wrap.append(lambda t: _Scripted(t, broken_restore))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", StepRequest("radio0", ("g",), (1,), dwell_s=10))
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert job.phase == "failed" and job.restore_pending
    assert job.error is not None and "boom" in job.error and job.error.endswith("Restore it")
    assert steps.busy("ap2") is None


async def test_a_cancelled_run_ends_failed_with_restore_offered(env: WifiEnv, tmp_path: Path) -> None:
    """v1.0b2 D7: a task cancelled while it waits (an app shutdown past its limit) does not stay running."""
    steps = _service(env, tmp_path, _Clock())
    await _run(steps, "ap2", StepRequest("radio0", ("g",), (1,), advance="manual"))
    await _until(lambda: _job(steps).phase == "waiting for Next")
    task = steps._controls["ap2"].task
    assert task is not None
    task.cancel()
    await _until(task.done)
    job = _job(steps)
    assert (job.phase, job.restore_pending) == ("failed", True)
    assert job.error == "radio0 was not restored: Restore it"
    assert steps.busy("ap2") is None


async def test_a_proven_step_is_kept_when_its_wait_loses_the_router(env: WifiEnv, tmp_path: Path) -> None:
    """v0.7 minor (#41): the step was proven on air; losing the connection while waiting for the station must
    not drop it from the results and the CSV."""
    steps: StepService | None = None

    def lost(command: str, n: int) -> CommandResult | None:
        waiting = _phase(steps) == "waiting for station"
        if waiting and command.startswith("ubus call network.wireless status"):
            raise TransportError("connection lost")
        return None

    env.wrap.append(lambda t: _Scripted(t, lost))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="F4:12:FA:F3:57:68", dwell_s=10)
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    job = _job(steps)
    assert [r.proven for r in job.results] == [True]
    assert job.error is not None and "connection lost" in job.error
    assert job.csv_path is not None and len(Path(job.csv_path).read_text().splitlines()) == 2


async def test_a_next_for_the_station_wait_does_not_skip_the_dwell(env: WifiEnv, tmp_path: Path) -> None:
    """v0.7 minor (#42): Next acts on the phase on screen; one pressed while the station came back is not
    carried into the dwell."""
    steps: StepService | None = None
    joined = '{"clients": {"f4:12:fa:f3:57:68": {"assoc": true, "authorized": true}}}'

    def back_with_a_next(command: str, n: int) -> CommandResult | None:
        if steps is not None and "get_clients" in command and _phase(steps) == "waiting for station":
            steps.next("ap2")  # pressed while the station re-joins
            return CommandResult(command, joined, "", 0)
        return None

    env.wrap.append(lambda t: _Scripted(t, back_with_a_next))  # type: ignore[arg-type,return-value]
    steps = _service(env, tmp_path, _Clock())
    req = StepRequest("radio0", ("g",), (1,), advance="rejoin", station="F4:12:FA:F3:57:68", dwell_s=10)
    await _run(steps, "ap2", req)
    await _until(lambda: _job(steps).phase in DONE)
    (result,) = _job(steps).results
    assert result.rejoined and result.ended_at is not None
    assert result.ended_at - result.started_at >= timedelta(seconds=10)  # the dwell ran


def _left_at_a_step(tmp_path: Path, options: dict[str, Any] | None = None) -> Path:
    """A saved file as a run stopped by Bench Guard leaves it."""
    base = dict.fromkeys(SAVED_OPTIONS) | {"channel": "6", "htmode": "HT20"}
    saved = options if options is not None else base
    record = PendingRestore(
        router_id="ap2", radio="radio0", saved_at=datetime(2026, 11, 16, 9, 0), options=saved
    )
    path = tmp_path / "steps" / "ap2-radio0.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(), encoding="utf-8")
    return path


async def test_restore_waits_for_a_system_job_as_start_does(env: WifiEnv, tmp_path: Path) -> None:
    """v0.7 minor (#45): Restore refuses while a reboot or a flash holds the router."""
    steps = _service(env, tmp_path, _Clock(), busy=[lambda router_id: "A reboot runs on AP2"])
    path = _left_at_a_step(tmp_path)
    with pytest.raises(StepBusy, match="^A reboot runs on AP2$"):
        await steps.restore("ap2", "radio0")
    assert path.exists()


async def test_a_saved_file_without_every_option_restores_nothing(env: WifiEnv, tmp_path: Path) -> None:
    steps = _service(env, tmp_path, _Clock())
    path = _left_at_a_step(tmp_path, {"channel": "6"})
    with pytest.raises(ValueError, match=r"ap2-radio0.json lacks htmode.*Remove that file"):
        await steps.restore("ap2", "radio0")
    assert path.exists()


async def test_start_checks_the_radio_name_before_any_file(env: WifiEnv, tmp_path: Path) -> None:
    """v1.0b1 final review minor: the name builds a file path, so it is checked before the path is probed."""
    steps = _service(env, tmp_path, _Clock())
    with pytest.raises(ValueError, match="is not a radio name"):
        await steps.start("ap2", StepRequest("../x", ("g",), (1,)), "0" * 16)
