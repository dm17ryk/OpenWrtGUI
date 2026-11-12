"""The Wi-Fi step-through (v0.7 plan D2-D10): every step proven on air, the radio restored at the end.

Each step is a Wi-Fi Apply of one pure mode, one channel and (optionally) one TX power, planned again from the
live router and compared with the preview before it runs. The radio's own options are saved to the data folder
before step 1 and applied back at the end, on Stop and at shutdown; a file left behind offers Restore at the
next start. If a harness run starts, the step-through stops at once and leaves the radio as it is (a reload
would disturb the run): the restore waits until Bench Guard is clear.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.probe.status import RouterStatus, ssids_on_air
from openwrtgui.rf.air import checked_ifname, get_clients
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.model import Mode
from openwrtgui.wifi.service import NOTHING, ApplyResult, Check, PreviewChanged, WifiService
from openwrtgui.wifi.state import RadioState, read_uci
from openwrtgui.wifi.step_csv import StepCsv
from openwrtgui.wifi.steps import (
    STEP_OVERHEAD_S,
    Advance,
    Step,
    StepRequest,
    expand_steps,
    joined,
    saved_ops,
    saved_options,
    step_request,
)

log = logging.getLogger(__name__)
WHAT = "A step-through"
StepPhase = Literal[
    "applying", "dwell", "waiting for station", "waiting for Next", "restoring", "done", "stopped", "failed"
]
WAITING = ("dwell", "waiting for station", "waiting for Next")
ENDED = ("done", "stopped", "failed")
Outcome = Literal["next", "stop", "guard", "error"]


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    mode: Mode
    channel: int
    txpower_dbm: int | None
    proven: bool
    checks: list[Check]
    beacon: str | None
    rejoin_s: float | None
    rejoined: bool | None  # None when the advance is not "station re-joins"
    started_at: datetime
    ended_at: datetime | None


class StepJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    radio: str
    phase: StepPhase
    index: int  # the step running or last run (1-based)
    total: int
    current: Step | None
    advance: Advance
    dwell_s: int
    station: str | None
    phase_ends_at: datetime | None  # the dwell or the re-join limit, for the countdown
    results: list[StepResult]
    restore_pending: bool
    csv_path: str | None
    started_at: datetime
    ended_at: datetime | None
    detail: str | None
    error: str | None


@dataclass(frozen=True)
class StepPlan:
    router_id: str
    radio: str
    request: StepRequest
    steps: tuple[Step, ...]
    step_lines: tuple[tuple[str, ...], ...]  # each step's lines as shown, the TX-mask line included
    restore_lines: tuple[str, ...]
    warnings: tuple[str, ...]  # an SSID of the radio on air on another router (plan D9)
    estimate_s: int
    step_changes: tuple[tuple[str, ...], ...] = field(default=(), repr=False)
    restore_changes: tuple[str, ...] = field(default=(), repr=False)

    @property
    def digest(self) -> str:
        """Over the request, every step's change lines and the restore lines: Start runs what was shown."""
        parts = [json.dumps(dataclasses.asdict(self.request), sort_keys=True)]
        parts += ["\n".join(lines) for lines in self.step_changes]
        parts.append("\n".join(self.restore_changes))
        return hashlib.sha256("\n--\n".join(parts).encode()).hexdigest()[:16]


class PendingRestore(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    radio: str
    saved_at: datetime
    options: dict[str, str | None]


class StepBusy(RouterBusy):
    """Another step-through, a System job or a flash holds the router (plan D8, 409)."""


@dataclass
class _Control:
    token: object
    saved: dict[str, str | None]
    csv: StepCsv
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    next: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class StepService:
    def __init__(
        self,
        *,
        wifi: WifiService,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        statuses: Mapping[str, RouterStatus],
        steps_dir: Path,
        documents: Path,
        busy: Sequence[Callable[[str], str | None]] = (),
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        tick_s: float = 1.0,
    ) -> None:
        self._wifi = wifi
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._statuses = statuses
        self._steps_dir = steps_dir
        self._documents = documents
        self._busy = busy
        self._clock = clock
        self._sleep = sleep
        self._tick_s = tick_s
        self._jobs: dict[str, StepJob] = {}
        self._controls: dict[str, _Control] = {}

    # ---------------------------------------------------------------- reading
    def _record_of(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    def job(self, router_id: str) -> StepJob | None:
        return self._jobs.get(router_id)

    def running(self, router_id: str) -> bool:
        job = self._jobs.get(router_id)
        return job is not None and job.phase not in ENDED

    def busy(self, router_id: str) -> str | None:
        """Why another job may not start on this router now (plan D8); None when it may."""
        job = self._jobs.get(router_id)
        if job is None or job.phase in ENDED:
            return None
        rec = self._routers.get(router_id)
        return f"A step-through runs on {rec.name if rec else router_id} {job.radio}"

    def live(self) -> list[str]:
        out = []
        for router_id, job in self._jobs.items():
            if job.phase not in ENDED:
                rec = self._routers.get(router_id)
                out.append(f"Step-through on {rec.name if rec else router_id} {job.radio}")
        return out

    def _saved_path(self, router_id: str, radio: str) -> Path:
        return self._steps_dir / f"{router_id}-{radio}.json"

    def pending(self) -> list[PendingRestore]:
        out = []
        for path in sorted(self._steps_dir.glob("*.json")) if self._steps_dir.is_dir() else []:
            with contextlib.suppress(OSError, ValidationError):
                out.append(PendingRestore.model_validate_json(path.read_text(encoding="utf-8")))
        return out

    # ---------------------------------------------------------------- preview
    def _on_air_elsewhere(self, rec: RouterRecord, radio: RadioState) -> tuple[str, ...]:
        out = []
        for other_id, status in self._statuses.items():
            other = self._routers.get(other_id)
            if other_id == rec.id or other is None:
                continue
            on_air = ssids_on_air(status)
            out += [
                f"{s.ssid} is already on air on {other.name}. The bench rule is one radio on air per SSID."
                for s in radio.ssids
                if s.ssid in on_air
            ]
        return tuple(out)

    async def _prepare(self, rec: RouterRecord, req: StepRequest) -> tuple[StepPlan, dict[str, str | None]]:
        state = await self._wifi.state(rec.id)
        radio = next((r for r in state.radios if r.name == req.radio), None)
        if radio is None:
            raise ValueError(f"{req.radio} is not a radio of {rec.name}")
        steps = expand_steps(req, radio.limits)
        saved = saved_options(await read_uci(await self._pool.get(rec)), req.radio)
        plans, restore = await self._wifi.plan_sequence(
            rec.id, req.radio, [step_request(s, req.radio) for s in steps], saved_ops(req.radio, saved)
        )
        per_step = STEP_OVERHEAD_S + (0 if req.advance == "manual" else req.dwell_s)
        plan = StepPlan(
            router_id=rec.id,
            radio=req.radio,
            request=req,
            steps=steps,
            step_lines=tuple(p.lines for p in plans),
            restore_lines=restore.lines,
            warnings=self._on_air_elsewhere(rec, radio),
            estimate_s=len(steps) * per_step,
            step_changes=tuple(p.change_lines for p in plans),
            restore_changes=restore.change_lines,
        )
        return plan, saved

    @staticmethod
    def _normal(req: StepRequest) -> StepRequest:
        return dataclasses.replace(req, station=req.station.lower()) if req.station else req

    async def preview(self, router_id: str, req: StepRequest) -> StepPlan:
        return (await self._prepare(self._record_of(router_id), self._normal(req)))[0]

    # ---------------------------------------------------------------- start, next, stop
    async def start(self, router_id: str, req: StepRequest, digest: str) -> StepJob:
        self._guard.require_clear()
        rec = self._record_of(router_id)
        req = self._normal(req)
        if (why := self.busy(rec.id)) is not None:
            raise StepBusy(why)
        for check in self._busy:
            if (why := check(rec.id)) is not None:
                raise StepBusy(why)
        if self._saved_path(rec.id, req.radio).exists():
            raise StepBusy(f"Restore {req.radio} on {rec.name} first: a step-through left it at a step")
        plan, saved = await self._prepare(rec, req)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        if plan.warnings:
            raise ValueError(plan.warnings[0])
        token = self._wifi.hold_radio(rec.id, req.radio, WHAT)
        try:
            csv = self._open(rec, req, saved)
        except BaseException:
            self._wifi.release_radio(token)
            raise
        now = self._clock()
        self._jobs[rec.id] = StepJob(
            router_id=rec.id,
            radio=req.radio,
            phase="applying",
            index=0,
            total=len(plan.steps),
            current=None,
            advance=req.advance,
            dwell_s=req.dwell_s,
            station=req.station,
            phase_ends_at=None,
            results=[],
            restore_pending=False,
            csv_path=str(csv.path),
            started_at=now,
            ended_at=None,
            detail=None,
            error=None,
        )
        ctl = _Control(token, saved, csv)
        self._controls[rec.id] = ctl
        ctl.task = asyncio.get_running_loop().create_task(self._runner(rec, req, plan, ctl))
        return self._jobs[rec.id]

    def _open(self, rec: RouterRecord, req: StepRequest, saved: dict[str, str | None]) -> StepCsv:
        """The saved options first (written whole, then renamed), then the CSV."""
        self._steps_dir.mkdir(parents=True, exist_ok=True)
        path = self._saved_path(rec.id, req.radio)
        record = PendingRestore(router_id=rec.id, radio=req.radio, saved_at=self._clock(), options=saved)
        part = path.with_suffix(".part")
        part.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        part.replace(path)
        stamp = self._clock().strftime("%Y%m%d-%H%M%S")
        try:
            return StepCsv(self._documents / "OpenWrtGUI" / f"steps-{rec.id}-{req.radio}-{stamp}.csv")
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def next(self, router_id: str) -> StepJob:
        job = self._jobs.get(router_id)
        ctl = self._controls.get(router_id)
        if job is None or ctl is None or job.phase not in WAITING:
            raise ValueError(f"Nothing waits for Next on {self._record_of(router_id).name}")
        ctl.next.set()
        return job

    async def stop(self, router_id: str) -> StepJob:
        job = self._jobs.get(router_id)
        if job is None:
            raise ValueError(f"No step-through on {self._record_of(router_id).name}")
        ctl = self._controls.get(router_id)
        if ctl is not None and job.phase not in ENDED:
            ctl.stop.set()
        return self._jobs[router_id]

    async def stop_all(self, limit_s: float) -> None:
        """Stop every step-through and wait for its restore (app shutdown, an update)."""
        tasks = []
        for router_id, ctl in self._controls.items():
            if self.running(router_id) and ctl.task is not None:
                ctl.stop.set()
                tasks.append(ctl.task)
        if tasks:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), limit_s)

    # ---------------------------------------------------------------- the runner
    def _update(self, router_id: str, **fields: Any) -> None:
        self._jobs[router_id] = self._jobs[router_id].model_copy(update=fields)

    def _live(self) -> str | None:
        state = self._guard.state()
        if not state.live:
            return None
        return state.reasons[0].text if state.reasons else "a harness run"

    def _keep(self, router_id: str, ctl: _Control, result: StepResult) -> None:
        self._update(router_id, results=[*self._jobs[router_id].results, result])
        ctl.csv.write(result)

    async def _runner(self, rec: RouterRecord, req: StepRequest, plan: StepPlan, ctl: _Control) -> None:
        outcome: Outcome = "next"
        error: str | None = None
        try:
            for step, changes in zip(plan.steps, plan.step_changes, strict=True):
                outcome, error = await self._step(rec, req, step, changes, ctl)
                if outcome != "next" or ctl.stop.is_set():
                    break
            if outcome == "guard":
                self._guard_stopped(rec, req)
            else:
                await self._restore_after(rec, req, ctl, error)
        except Exception as exc:  # never leave the radio at a step without saying so
            log.exception("step-through on %s failed", rec.id)
            await self._restore_after(rec, req, ctl, f"The step-through failed: {exc}")
        finally:
            self._wifi.release_radio(ctl.token)
            ctl.csv.close()

    async def _step(
        self, rec: RouterRecord, req: StepRequest, step: Step, changes: tuple[str, ...], ctl: _Control
    ) -> tuple[Outcome, str | None]:
        self._update(rec.id, phase="applying", index=step.index, current=step, phase_ends_at=None)
        if ctl.stop.is_set():
            return "stop", None
        if self._live():
            return "guard", None
        started = self._clock()
        one = step_request(step, req.radio)
        try:
            live, _restore = await self._wifi.plan_sequence(rec.id, req.radio, [one], [])
            if live[0].change_lines != changes:
                return "error", (
                    f"{rec.name} {req.radio} changed during the step-through: "
                    f"step {step.index} is no longer the previewed one"
                )
            result = await self._wifi.apply(rec.id, one, live[0].digest, holder=ctl.token, allow_empty=True)
        except GuardLocked:
            return "guard", None
        except TransportError as exc:
            return "error", f"Lost the connection to {rec.name}: {exc}"
        except ValueError as exc:
            return "error", str(exc)
        if result.error is not None:
            return ("guard", None) if self._live() else ("error", result.error)
        beacon = next((c.detail for c in result.checks if c.name == "beacon rate"), None)
        base = StepResult(
            index=step.index,
            mode=step.mode,
            channel=step.channel,
            txpower_dbm=step.txpower_dbm,
            proven=result.verified,
            checks=list(result.checks),
            beacon=beacon,
            rejoin_s=None,
            rejoined=None,
            started_at=started,
            ended_at=None,
        )
        if not result.verified:  # plan D4: recorded, no dwell, the run goes on
            self._keep(rec.id, ctl, base.model_copy(update={"ended_at": self._clock()}))
            return ("stop", None) if ctl.stop.is_set() else ("next", None)
        waited: Outcome = "next"
        if req.advance == "rejoin":
            waited, rejoin_s = await self._rejoin(rec, req, ctl, started)
            base = base.model_copy(update={"rejoin_s": rejoin_s, "rejoined": rejoin_s is not None})
            if waited == "next" and rejoin_s is not None:
                waited = await self._wait(rec.id, ctl, req.dwell_s, "dwell")
        else:
            seconds = None if req.advance == "manual" else req.dwell_s
            waited = await self._wait(
                rec.id, ctl, seconds, "waiting for Next" if seconds is None else "dwell"
            )
        self._keep(rec.id, ctl, base.model_copy(update={"ended_at": self._clock()}))
        return waited, None

    async def _wait(self, router_id: str, ctl: _Control, seconds: float | None, phase: StepPhase) -> Outcome:
        ends = self._clock() + timedelta(seconds=seconds) if seconds is not None else None
        self._update(router_id, phase=phase, phase_ends_at=ends)
        waited = 0.0
        while True:
            if ctl.stop.is_set():
                return "stop"
            if ctl.next.is_set():
                ctl.next.clear()
                return "next"
            if self._live():
                return "guard"
            if seconds is not None and waited >= seconds:
                return "next"
            await self._sleep(self._tick_s)
            waited += self._tick_s

    async def _ap_ifname(self, rec: RouterRecord, radio: str) -> str | None:
        status = (await ubus_call(await self._pool.get(rec), "network.wireless", "status") or {}).get(
            radio, {}
        )
        name = next((str(i["ifname"]) for i in status.get("interfaces", []) if i.get("ifname")), None)
        return checked_ifname(name) if name else None

    async def _rejoin(
        self, rec: RouterRecord, req: StepRequest, ctl: _Control, started: datetime
    ) -> tuple[Outcome, float | None]:
        """Read hostapd's clients every tick until the station is back; None when it is not by the limit.
        The time counts from the step's start (the reload drops the station), the limit from its proof."""
        limit = req.rejoin_limit_s
        self._update(
            rec.id, phase="waiting for station", phase_ends_at=self._clock() + timedelta(seconds=limit)
        )
        ifname = await self._ap_ifname(rec, req.radio)
        t = await self._pool.get(rec)
        waited = 0.0
        while waited < limit:
            if ctl.stop.is_set():
                return "stop", None
            if ctl.next.is_set():
                ctl.next.clear()
                return "next", None
            if self._live():
                return "guard", None
            if ifname is not None and req.station:
                with contextlib.suppress(TransportError, ValueError):
                    clients = json.loads((await t.run(get_clients(ifname))).stdout or "{}")
                    if joined(clients, req.station):
                        return "next", (self._clock() - started).total_seconds()
            await self._sleep(self._tick_s)
            waited += self._tick_s
        return "next", None

    # ---------------------------------------------------------------- restore
    async def _apply_saved(
        self, rec: RouterRecord, radio: str, saved: Mapping[str, str | None], token: object
    ) -> tuple[ApplyResult | None, str | None]:
        """(result, why it is not proven); (None, None) when the radio already reads as saved."""
        try:
            result = await self._wifi.apply_ops(rec.id, radio, saved_ops(radio, saved), holder=token)
        except ValueError as exc:
            return (None, None) if str(exc) == NOTHING else (None, str(exc))
        except GuardLocked:
            return None, f"Bench Guard is live: {self._live() or 'a harness run'}"
        except TransportError as exc:
            return None, f"Lost the connection to {rec.name}: {exc}"
        if result.verified:
            return result, None
        failed = ", ".join(f"{c.name}: {c.detail}" for c in result.checks if c.ok is False)
        return result, result.error or failed or "not verified"

    async def _restore_after(
        self, rec: RouterRecord, req: StepRequest, ctl: _Control, error: str | None
    ) -> None:
        self._update(rec.id, phase="restoring", current=None, phase_ends_at=None, error=error)
        _result, why = await self._apply_saved(rec, req.radio, ctl.saved, ctl.token)
        now = self._clock()
        if why is None:
            self._saved_path(rec.id, req.radio).unlink(missing_ok=True)
            phase: StepPhase = "failed" if error else "stopped" if ctl.stop.is_set() else "done"
            self._update(rec.id, phase=phase, restore_pending=False, ended_at=now)
            return
        text = f"{error}; " if error else ""
        self._update(
            rec.id,
            phase="failed",
            restore_pending=True,
            ended_at=now,
            error=f"{text}{req.radio} was not restored ({why}): Restore it",
        )

    def _guard_stopped(self, rec: RouterRecord, req: StepRequest) -> None:
        job = self._jobs[rec.id]
        self._update(
            rec.id,
            phase="stopped",
            restore_pending=True,
            phase_ends_at=None,
            ended_at=self._clock(),
            error=(
                f"Stopped by Bench Guard ({self._live() or 'a harness run'}): {req.radio} is left at step "
                f"{job.index}; restore it once the run is over"
            ),
        )

    async def restore(self, router_id: str, radio: str) -> ApplyResult:
        """A restore a step-through left pending (Bench Guard stopped it, or the app ended before it)."""
        self._guard.require_clear()
        rec = self._record_of(router_id)
        if (why := self.busy(rec.id)) is not None:
            raise StepBusy(why)
        path = self._saved_path(rec.id, radio)
        try:
            saved = PendingRestore.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            raise ValueError(
                f"Nothing to restore: no step-through left {radio} on {rec.name} at a step"
            ) from None
        token = self._wifi.hold_radio(rec.id, radio, WHAT)
        try:
            result, why = await self._apply_saved(rec, radio, saved.options, token)
        finally:
            self._wifi.release_radio(token)
        if why is not None:
            raise ValueError(f"{radio} on {rec.name} was not restored: {why}")
        path.unlink(missing_ok=True)
        if rec.id in self._jobs:
            self._update(rec.id, restore_pending=False)
        return result or ApplyResult(rec.id, radio, False, True, (), None)
