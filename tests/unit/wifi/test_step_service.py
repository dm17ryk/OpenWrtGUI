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
from openwrtgui.transport.base import CommandResult, Transport
from openwrtgui.wifi.service import PreviewChanged
from openwrtgui.wifi.step_service import StepBusy, StepJob, StepService
from openwrtgui.wifi.steps import StepRequest

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
