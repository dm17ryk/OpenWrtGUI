"""Recover (spec 4.2, 4.9): a per-router background job that diagnoses the LTE modem, then climbs a ladder of
rungs and stops as soon as LTE works. It never reboots the router; it says so when nothing helped.

Every command goes through LteService (audited, refused during a harness run). Stop and a harness run put back
what the running rung took down (online after low_power, ifup lte after ifdown lte), then end."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.lte import commands as c
from openwrtgui.lte.service import DISCONNECT_S, DROPS, HARNESS_STOPPED, LteService
from openwrtgui.lte.setups import SetupStore, SetupUnreadable, setup_change
from openwrtgui.lte.state import LteState, lte_works
from openwrtgui.net.apply import NOTHING
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport, TransportError
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

RecoverPhase = Literal["running", "works", "recovered", "not recovered", "stopped", "failed"]
RungOutcome = Literal["skipped", "not needed", "works", "not yet", "failed"]
RUNGS = (
    "Put back the saved setup",
    "Reconnect",
    "Clear QMI state",
    "Turn off the modem's autoconnect",
    "Restart the modem",
)
ONLY_IF = "  # only if LTE does not work after the step before"
AUTOCONNECT_TRIES = (
    10  # the stock firmware's usbmodem_set_defaults tries ten times, about 1 s apart (spec 4.9)
)
AUTOCONNECT_GAP_S = 1.0
WORKS = "LTE works; nothing to do."
DIFFERS = "Its settings differ from the good setup saved {date}: use Reconfigure to put them back."
RECOVERED = "LTE works again after: {rung}."
NOT_RECOVERED = (
    "LTE did not come back. Reboot the router (System › Reboot), then power-cycle it if that does not help."
)
FAILED = "{command}: {reason}; the modem was left {where}."
NO_ANSWER = "{command}: {name} did not answer."
NOT_DOWN = "{command} not sent: lte was not down after {s:g} s"
SYNC_WAITS = "{rung} sends --sync only once lte is down and no uqmi runs (up to {s:g} s); else it skips it."


class RungResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    outcome: RungOutcome | None = None  # None: not reached yet
    detail: str | None = None


class LteRecoverJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    phase: RecoverPhase
    diagnosis: list[str]
    rungs: list[RungResult]
    current: int | None
    started_at: datetime
    ended_at: datetime | None
    detail: str | None
    error: str | None


@dataclass(frozen=True)
class RecoverPreview:
    router_id: str
    lines: tuple[str, ...]
    warnings: tuple[str, ...]
    digest: str


class LteRecoverBusy(RouterBusy):
    """Another LTE job, an LTE action, a step-through, a System job or a flash holds the router (409)."""


class _Stopped(Exception):
    """Stop or a harness run: the rung puts back what it took down, then the job ends."""

    def __init__(self, harness: bool) -> None:
        super().__init__("stopped")
        self.harness = harness


class _Failed(Exception):
    """A rung-5 command failed, or the router stopped answering: the job ends "failed"."""


@dataclass
class _Run:
    rec: RouterRecord
    t: Transport
    device: str
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    pending: dict[str, tuple[str, str]] = field(default_factory=dict)  # what to put back: line, where if not
    task: asyncio.Task[None] | None = None


def _digest(lines: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def diagnose(state: LteState) -> list[str]:
    """What is wrong, from the read Recover starts with (spec 4.2)."""
    out = []
    if state.registration != "registered":
        out.append("not registered")
    if state.up is not True:
        out.append("no session")
    elif state.data_handle is not True:
        out.append("session up but no packet-data handle")
    elif not state.ipv4:
        out.append("no address")
    return out


class LteRecover:
    def __init__(
        self,
        *,
        lte: LteService,
        setups: SetupStore,
        routers: RouterStore,
        guard: BenchGuard,
        busy: Sequence[Callable[[str], str | None]] = (),
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._lte = lte
        self._setups = setups
        self._routers = routers
        self._guard = guard
        self._busy = busy
        self._clock = clock
        self._sleep = sleep
        self._jobs: dict[str, LteRecoverJob] = {}
        self._runs: dict[str, _Run] = {}
        self._starting: set[str] = set()
        self.autoconnect_gap_s = AUTOCONNECT_GAP_S

    # ---------------------------------------------------------------- reading
    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    def job(self, router_id: str) -> LteRecoverJob | None:
        return self._jobs.get(router_id)

    def _running(self, router_id: str) -> bool:
        job = self._jobs.get(router_id)
        return router_id in self._starting or (job is not None and job.phase == "running")

    def busy(self, router_id: str) -> str | None:
        if not self._running(router_id):
            return None
        rec = self._routers.get(router_id)
        return f"LTE recovery runs on {rec.name if rec else router_id}"

    def live(self) -> list[str]:
        out = []
        for router_id in sorted({*self._starting, *self._jobs}):
            if self._running(router_id):
                rec = self._routers.get(router_id)
                out.append(f"LTE recovery on {rec.name if rec else router_id}")
        return out

    async def finished(self, router_id: str) -> LteRecoverJob | None:
        """The job once its runner ended (tests, and stop_all)."""
        run = self._runs.get(router_id)
        if run is not None and run.task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await run.task
        return self._jobs.get(router_id)

    # ---------------------------------------------------------------- preview
    async def _setup_lines(self, rec: RouterRecord) -> tuple[list[str], list[str]]:
        """Rung 1's lines (the settings preview, secrets masked) and the warnings about the saved setup. A
        setup that cannot be read or put back is named here and never blocks the other steps (review I2,
        I3)."""
        try:
            setup = self._setups.get(rec.id)
        except SetupUnreadable as exc:
            return [], [f"{exc}: Recover starts at Reconnect."]
        if setup is None:
            return [], [f"No good setup is saved for {rec.name}: Recover starts at Reconnect."]
        try:
            plan = await self._lte.plan_setup(rec.id, rec.id, self._setups)
        except ValueError as exc:
            if str(exc).startswith(NOTHING):  # the settings match the saved setup
                return [], []
            return [], [f"The saved good setup cannot be put back: {exc}"]
        return list(plan.lines), list(plan.warnings)

    async def preview(self, router_id: str) -> RecoverPreview:
        rec = self._record(router_id)
        device = await self._lte.lte_device(router_id)
        if device is None:
            raise ValueError("Recover needs the modem's QMI device (/dev/cdc-wdmN) in network.lte.device")
        first, notes = await self._setup_lines(rec)
        rungs = [
            [c.IFDOWN_LTE, c.IFUP_LTE],
            [c.IFDOWN_LTE, c.sync(device), c.IFUP_LTE],
            [c.IFDOWN_LTE, c.autoconnect_off(device), c.IFUP_LTE],
            [
                c.IFDOWN_LTE,
                c.set_opmode(device, "low_power"),
                c.OPMODE(device),
                c.set_opmode(device, "online"),
                c.OPMODE(device),
                c.IFUP_LTE,
            ],
        ]
        lines = [f"{line}{ONLY_IF}" for line in first] + [
            f"{line}{ONLY_IF}" for rung in rungs for line in rung
        ]
        warnings = [
            DROPS.format(name=rec.name),
            SYNC_WAITS.format(rung=RUNGS[2], s=DISCONNECT_S),
            f"{RUNGS[3]} sends its command up to {AUTOCONNECT_TRIES} times, {AUTOCONNECT_GAP_S:g} s apart.",
            *notes,
        ]
        return RecoverPreview(rec.id, tuple(lines), tuple(warnings), _digest(lines))

    # ---------------------------------------------------------------- start, stop
    async def start(self, router_id: str, digest: str) -> LteRecoverJob:
        self._guard.require_clear()
        rec = self._record(router_id)
        for check in (self.busy, self._lte.action_busy, *self._busy):
            if (why := check(rec.id)) is not None:
                raise LteRecoverBusy(why)
        self._starting.add(rec.id)  # no await since the checks: nothing else got in between
        try:
            preview = await self.preview(rec.id)
            if preview.digest != digest:
                raise PreviewChanged(rec.name)
            device = await self._lte.lte_device(rec.id)
            if device is None:  # the preview checked it; the router's config may have changed since
                raise ValueError("Recover needs the modem's QMI device (/dev/cdc-wdmN) in network.lte.device")
            run = _Run(rec, await self._lte.transport(rec), device)
            self._jobs[rec.id] = LteRecoverJob(
                router_id=rec.id,
                phase="running",
                diagnosis=[],
                rungs=[RungResult(name=name) for name in RUNGS],
                current=None,
                started_at=self._clock(),
                ended_at=None,
                detail=None,
                error=None,
            )
            self._runs[rec.id] = run
            run.task = asyncio.get_running_loop().create_task(self._runner(run))
            return self._jobs[rec.id]
        finally:
            self._starting.discard(rec.id)

    def request_stop(self, router_id: str) -> None:
        """Stop at the next safe point: before the next command or check."""
        run = self._runs.get(router_id)
        if run is not None and self._running(router_id):
            run.stop.set()

    async def stop(self, router_id: str) -> LteRecoverJob | None:
        self.request_stop(router_id)
        return self._jobs.get(router_id)

    async def stop_all(self, limit_s: float) -> None:
        """Stop every job at its next safe point and wait for its put-back (app shutdown, an update)."""
        tasks = []
        for router_id, run in self._runs.items():
            if self._running(router_id) and run.task is not None:
                run.stop.set()
                tasks.append(run.task)
        if tasks:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), limit_s)

    # ---------------------------------------------------------------- the runner
    def _update(self, router_id: str, **fields: Any) -> None:
        self._jobs[router_id] = self._jobs[router_id].model_copy(update=fields)

    def _rung(self, router_id: str, index: int, outcome: RungOutcome, detail: str | None = None) -> None:
        rungs = list(self._jobs[router_id].rungs)
        rungs[index] = RungResult(name=RUNGS[index], outcome=outcome, detail=detail)
        self._update(router_id, rungs=rungs)

    def _end(
        self, run: _Run, phase: RecoverPhase, *, detail: str | None = None, error: str | None = None
    ) -> None:
        rungs = [
            r if r.outcome is not None else RungResult(name=r.name, outcome="not needed")
            for r in self._jobs[run.rec.id].rungs
        ]
        self._update(
            run.rec.id,
            phase=phase,
            detail=detail,
            error=error,
            current=None,
            rungs=rungs,
            ended_at=self._clock(),
        )

    @staticmethod
    def _left(run: _Run, text: str) -> str:
        """Spec anti-goal: never leave the modem in low power (or LTE down) without the result saying so."""
        where = (
            "in low power" if "online" in run.pending else "with LTE down" if "ifup" in run.pending else None
        )
        if where is None or "the modem was left" in text:
            return text
        return f"{text.rstrip('.')}; the modem was left {where}."

    async def _runner(self, run: _Run) -> None:
        try:
            await self._climb(run)
        except _Stopped as stopped:
            await self._stopped(run, stopped.harness)
        except _Failed as failed:
            self._end(run, "failed", error=self._left(run, str(failed)))
        except asyncio.CancelledError:  # stop_all ran out of time: say where the modem is, then end
            self._end(run, "stopped", error=self._left(run, "Recover was cancelled before it finished"))
            raise
        except Exception as exc:  # never left "running"
            log.exception("LTE recovery on %s failed", run.rec.id)
            self._end(run, "failed", error=self._left(run, f"Recover failed: {exc}"))
        finally:
            if self._jobs[run.rec.id].phase == "running":
                self._end(run, "failed", error=self._left(run, "Recover ended without a result"))

    async def _climb(self, run: _Run) -> None:
        rec = run.rec
        state = await self._lte.state(rec.id)
        diagnosis = diagnose(state)
        try:
            setup = self._setups.get(rec.id)
        except SetupUnreadable:  # the preview named it; Recover starts at Reconnect
            setup = None
        differs: list[str] = []
        broken: str | None = (
            None  # a setup that cannot become a settings change: rung 1 fails, the job goes on
        )
        if setup is not None:
            rows, values = await self._lte.setup_values(rec.id)
            try:
                change = setup_change(setup, rows, values, same_router=True)
            except ValueError as exc:
                broken = str(exc)
                change = None
            changed = (
                [
                    *(k for k, v in vars(change.settings).items() if v is not None and k != "edits"),
                    *(e.name for e in change.settings.edits),
                ]
                if change is not None
                else []
            )
            differs = sorted(changed)
            if differs:
                date = f"{setup.saved_at:%Y-%m-%d}"
                diagnosis.append(f"settings differ from the good setup saved {date}: {', '.join(differs)}")
        self._update(rec.id, diagnosis=diagnosis)
        if lte_works(state):
            detail = WORKS
            if differs and setup is not None:
                detail = f"{WORKS} {DIFFERS.format(date=f'{setup.saved_at:%Y-%m-%d}')}"
            self._end(run, "works", detail=detail)
            return
        rungs: tuple[Callable[[_Run], Awaitable[str | None]], ...] = (
            self._put_back_setup,
            self._reconnect,
            self._clear_qmi,
            self._autoconnect_off,
            self._restart,
        )
        for index, rung in enumerate(rungs):
            self._check(run)
            if index == 0 and broken is not None:
                self._rung(rec.id, 0, "failed", f"the saved good setup cannot be put back: {broken}")
                continue
            if index == 0 and not differs:
                self._rung(rec.id, 0, "skipped", "no good setup saved" if setup is None else "settings match")
                continue
            self._update(rec.id, current=index)
            # the pool's live connection: another apply may have replaced the one the job started with
            run.t = await self._lte.transport(rec)
            problem = await rung(run)
            if problem:  # shown even if a Stop or a harness run ends the job during the wait
                self._rung(rec.id, index, "failed", problem)
            works = await self._wait_works(run)
            if works:
                self._rung(rec.id, index, "works", problem)
                self._end(run, "recovered", detail=RECOVERED.format(rung=RUNGS[index]))
                return
            self._rung(rec.id, index, "failed" if problem else "not yet", problem)
        self._end(run, "not recovered", detail=NOT_RECOVERED)

    def _check(self, run: _Run) -> None:
        """Before every command and every wait: a harness run or Stop ends the job (after the put-back)."""
        if self._guard.state().live:
            raise _Stopped(harness=True)
        if run.stop.is_set():
            raise _Stopped(harness=False)

    async def _send(self, run: _Run, command: str) -> CommandResult:
        self._check(run)
        try:
            async with self._lte.write_lock(run.rec.id):
                return await self._lte.run(run.rec, run.t, command)
        except GuardLocked as exc:
            raise _Stopped(harness=True) from exc
        except TransportError as exc:
            raise _Failed(NO_ANSWER.format(command=command, name=run.rec.name)) from exc

    async def _down(self, run: _Run) -> str | None:
        done = await self._send(run, c.IFDOWN_LTE)
        run.pending["ifup"] = (c.IFUP_LTE, "with LTE down")
        return None if done.ok else f"{c.IFDOWN_LTE}: {_reason(done)}"

    async def _up(self, run: _Run) -> str | None:
        done = await self._send(run, c.IFUP_LTE)
        if done.ok:
            run.pending.pop("ifup", None)
            return None
        return f"{c.IFUP_LTE}: {_reason(done)}"

    async def _cycle(self, run: _Run, middle: Callable[[], Awaitable[str | None]]) -> str | None:
        """ifdown lte, the middle step, ifup lte (rungs 2-4): a failure is recorded; the ifup still runs."""
        problem = await self._down(run)
        if problem is None:
            problem = await middle()
        up = await self._up(run)
        return problem or up

    async def _put_back_setup(self, run: _Run) -> str | None:
        """Rung 1. A setup that cannot become a change, a preview that moved, or another writer: the rung
        fails, says why, and the job goes on (spec 4.2; final review I3)."""
        try:
            plan = await self._lte.plan_setup(run.rec.id, run.rec.id, self._setups)
            self._check(run)
            result = await self._lte.apply_setup(
                run.rec.id, run.rec.id, self._setups, plan.digest, recover=True
            )
        except GuardLocked as exc:
            raise _Stopped(harness=True) from exc
        except TransportError as exc:
            raise _Failed(NO_ANSWER.format(command="the settings change", name=run.rec.name)) from exc
        except (ValueError, PreviewChanged, RouterBusy) as exc:
            return f"the settings change: {exc}"
        # the rollback runner reconnects (pool.drop): the next steps use the pool's new connection (PR #82)
        run.t = await self._lte.transport(run.rec)
        if result.error:  # applied and still an error, e.g. confirmed after a harness run began
            return f"the settings change: {result.error}"
        return None if result.applied else "the settings change was not applied"

    async def _reconnect(self, run: _Run) -> str | None:
        async def nothing() -> str | None:
            return None

        return await self._cycle(run, nothing)

    async def _clear_qmi(self, run: _Run) -> str | None:
        async def sync() -> str | None:
            if not await self._wait_down(run):  # --sync would release the client of a teardown still running
                return NOT_DOWN.format(command=c.sync(run.device), s=DISCONNECT_S)
            done = await self._send(run, c.sync(run.device))
            return None if done.ok else f"{c.sync(run.device)}: {_reason(done)}"

        return await self._cycle(run, sync)

    async def _autoconnect_off(self, run: _Run) -> str | None:
        line = c.autoconnect_off(run.device)

        async def turn_off() -> str | None:
            reason = ""
            for attempt in range(AUTOCONNECT_TRIES):
                if attempt:
                    await self._sleep(self.autoconnect_gap_s)
                done = await self._send(run, line)
                reason = _reason(done)
                if done.ok or reason == c.NO_EFFECT:  # "No effect": autoconnect is already off
                    return None
            return f"{line}: {reason} ({AUTOCONNECT_TRIES} tries)"

        return await self._cycle(run, turn_off)

    async def _restart(self, run: _Run) -> str | None:
        """ifdown lte, then Reboot modem's sequence. A failed command ends the job, saying where the modem
        is."""
        problem = await self._down(run)
        if problem is not None:
            await self._fail_restart(run, c.IFDOWN_LTE, problem.split(": ", 1)[-1])
        low, online = c.set_opmode(run.device, "low_power"), c.set_opmode(run.device, "online")
        done = await self._send(run, low)
        if not done.ok:
            await self._fail_restart(run, low, _reason(done))
        run.pending["online"] = (online, "in low power")
        if not await self._readback(run, "low_power"):
            await self._fail_restart(run, low, "the modem did not report low_power")
        done = await self._send(run, online)
        if not done.ok:
            raise _Failed(FAILED.format(command=online, reason=_reason(done), where="in low power"))
        if not await self._readback(run, "online"):
            raise _Failed(
                FAILED.format(command=online, reason="the modem did not report online", where="in low power")
            )
        run.pending.pop("online", None)
        up = await self._up(run)
        if up is not None:
            raise _Failed(
                FAILED.format(command=c.IFUP_LTE, reason=up.split(": ", 1)[-1], where="with LTE down")
            )
        return None

    async def _readback(self, run: _Run, mode: str) -> bool:
        self._check(run)
        try:
            async with self._lte.write_lock(run.rec.id):
                return await self._lte.readback(run.rec, run.t, c.OPMODE(run.device), mode)
        except GuardLocked as exc:
            raise _Stopped(harness=True) from exc
        except TransportError as exc:
            raise _Failed(NO_ANSWER.format(command=c.OPMODE(run.device), name=run.rec.name)) from exc

    async def _fail_restart(self, run: _Run, line: str, reason: str) -> None:
        """Rung 5 failed before online: what it took down is put back first (online, then ifup lte), so the
        result says where the modem really is; then the job ends."""
        where = "online"
        for key in ("online", "ifup"):
            if key not in run.pending:
                continue
            command, left = run.pending[key]
            done = await self._send(run, command)
            if not done.ok:
                where = left
                break
            run.pending.pop(key)
        raise _Failed(FAILED.format(command=line, reason=reason, where=where))

    async def _wait_down(self, run: _Run) -> bool:
        """After `ifdown lte`: until lte is down and qmi.sh's teardown is over, up to DISCONNECT_S."""
        for attempt in range(max(1, int(DISCONNECT_S / self._lte.nominal_poll_s))):
            self._check(run)
            if attempt:
                await self._lte.pause()
            if await self._lte.down_now(run.t):
                return True
        return False

    async def _wait_works(self, run: _Run) -> bool:
        limit = max(1, int(self._lte.connect_s / self._lte.nominal_poll_s))
        for attempt in range(limit):
            self._check(run)
            if attempt:
                await self._lte.pause()
            if await self._lte.works_now(run.t):
                return True
        return False

    async def _stopped(self, run: _Run, harness: bool) -> None:
        """Put back what the running rung took down: online first, then ifup lte. Past Bench Guard only when a
        harness run is live (spec 4.2: "Finish putting back")."""
        order = [run.pending[k] for k in ("online", "ifup") if k in run.pending]
        if harness or (order and self._guard.state().live):
            await self._put_back_locked(run, order)
            return
        for line, where in order:
            try:
                async with self._lte.write_lock(run.rec.id):
                    done = await self._lte.run(run.rec, run.t, line)
            except GuardLocked:
                await self._put_back_locked(run, order[order.index((line, where)) :])
                return
            except TransportError:  # final review I1: say where the modem was left, never "no result"
                self._end(
                    run,
                    "stopped",
                    error=f"{line}: {run.rec.name} did not answer; the modem was left {where}.",
                )
                return
            if not done.ok:
                self._end(
                    run, "stopped", error=FAILED.format(command=line, reason=_reason(done), where=where)
                )
                return
        works = await self._lte.works_now(run.t)
        self._end(run, "stopped", detail="Stopped; LTE works." if works else "Stopped; LTE does not work.")

    async def _put_back_locked(self, run: _Run, order: list[tuple[str, str]]) -> None:
        """The put-back past Bench Guard, still under the router's write lock (PR #82 review)."""
        async with self._lte.write_lock(run.rec.id):
            result = await self._lte.put_back(run.rec, run.t, order)
        self._harness_put_back(run, result)

    def _harness_put_back(self, run: _Run, result: str) -> None:
        if result == HARNESS_STOPPED:
            self._end(run, "stopped", detail=result)
        else:  # a put-back line failed: the text names it and where the modem was left
            self._end(run, "stopped", error=result)


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"
