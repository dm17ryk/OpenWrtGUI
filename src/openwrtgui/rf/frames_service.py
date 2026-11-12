"""Frame analysis (v0.7 plan D12): short tcpdump windows on the shared monitor interface, summed on the PC.

Off by default and only with the radio on air. Starting it adds the monitor (a write: refused during a run)
and shows the exact commands first. Each window is a background read like RF live's samples, not audited one
by one; the audit gets the monitor's add, its flags, its removal and one line naming the window command. It
stops on Stop, when the last RF viewer leaves, when Bench Guard goes live (the monitor is removed: cleanup),
when the radio stays parked, after 30 minutes, or when the router stops answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited
from openwrtgui.rf.air import (
    FRAME_EVERY_S,
    FRAME_WINDOW,
    FRAME_WINDOW_S,
    FRAMES_LIMIT_S,
    MONITOR_FLAGS,
    checked_ifname,
)
from openwrtgui.rf.frames import FrameWindow, combine, summarize
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport, TransportError, ubus_call
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.monitor import DEL, MonitorLeases, add_command
from openwrtgui.wifi.parse import parse_iw_dev
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)
SCREEN = "RF live"
PARKED_WINDOWS = 3  # a step's reload takes the radio down for a moment: only a radio that stays down stops it
FAILURES = 2
REDONE = "monitor added again after a Wi-Fi reload"
LIMIT = "Stopped after 30 minutes: frame analysis costs router CPU"
CPU = "Costs router CPU: tcpdump runs 3 s of every 5 s for up to 30 minutes."


@dataclass(frozen=True)
class FramePlan:
    lines: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def digest(self) -> str:
        return hashlib.sha256("\n".join(self.lines).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class FrameState:
    running: bool = False
    started_at: datetime | None = None
    ends_at: datetime | None = None
    windows: int = 0
    fcs_reported: bool = True
    last: FrameWindow | None = None
    totals: FrameWindow | None = None
    note: str | None = None
    error: str | None = None  # why it stopped, when not by Stop


class FrameAnalyzer:
    def __init__(
        self,
        router_id: str,
        radio: str,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        monitors: MonitorLeases,
        publish: Callable[[dict[str, Any]], None],
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        limit_s: float = FRAMES_LIMIT_S,
    ) -> None:
        self.router_id = router_id
        self.radio = radio
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._monitors = monitors
        self._publish = publish
        self._clock = clock
        self._sleep = sleep
        self._limit_s = limit_s
        self._state = FrameState()
        self._task: asyncio.Task[None] | None = None
        self._holder = f"frames {radio}"
        self._start_lock = asyncio.Lock()
        self._stopping = False  # one Stop cancels the loop; later ones wait for its cleanup
        self._flags_at = 0  # the monitor's generation the flags were set on

    def state(self) -> FrameState:
        return self._state

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---------------------------------------------------------------- where
    async def _where(self) -> tuple[RouterRecord, Transport, str, set[str]]:
        rec = self._routers.get(self.router_id)
        if rec is None:
            raise ValueError(f"Unknown router {self.router_id}")
        t = await self._pool.get(rec)
        status = (await ubus_call(t, "network.wireless", "status") or {}).get(self.radio)
        if status is None:
            raise ValueError(f"{self.radio} is not a radio of {rec.name}")
        ifnames = {str(i["ifname"]) for i in status.get("interfaces", []) if i.get("ifname")}
        if not status.get("up") or not ifnames:
            raise ValueError(f"{self.radio} is parked: nothing of its own to analyse")
        phy = (await ubus_call(t, "iwinfo", "phyname", {"section": self.radio}) or {}).get("phyname", "phy0")
        own = {
            i.addr.lower()
            for i in parse_iw_dev((await t.run("iw dev")).stdout)
            if i.ifname in ifnames and i.addr
        }
        return rec, t, checked_ifname(str(phy)), own

    def _plan(self, phy: str) -> FramePlan:
        lines = (
            add_command(phy, clear_leftover=True),
            MONITOR_FLAGS,
            f"{FRAME_WINDOW}  # every {FRAME_EVERY_S} s, for up to {FRAMES_LIMIT_S // 60} minutes",
            DEL,
        )
        return FramePlan(lines, (CPU,))

    async def preview(self) -> FramePlan:
        _rec, _t, phy, _own = await self._where()
        return self._plan(phy)

    def _run_fn(self, rec: RouterRecord, t: Transport) -> Callable[[str, bool], Awaitable[CommandResult]]:
        async def run(command: str, require_guard: bool) -> CommandResult:
            return await run_audited(
                t,
                command,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                source="user" if require_guard else "app",
                require_guard=require_guard,
            )

        return run

    # ---------------------------------------------------------------- start and stop
    async def start(self, digest: str) -> FrameState:
        async with self._start_lock:  # two Starts at once run one analysis
            if self.running:
                return self._state
            return await self._start(digest)

    async def _start(self, digest: str) -> FrameState:
        self._guard.require_clear()
        rec, t, phy, own = await self._where()
        if self._plan(phy).digest != digest:
            raise PreviewChanged(rec.name)
        run = self._run_fn(rec, t)
        async with self._pool.write_lock(rec.id):
            await self._monitors.acquire(rec.id, self._holder, phy, t, run)
            try:
                fcs = (await run(MONITOR_FLAGS, True)).ok
            except BaseException:  # the router dropped or a run started: let go of the monitor again
                with contextlib.suppress(TransportError):
                    await self._monitors.release(rec.id, self._holder, run)
                raise
            self._flags_at = self._monitors.generation(rec.id)
        self._stopping = False
        self._audit.record(
            router=rec.id,
            screen=SCREEN,
            command=f"frame analysis: {FRAME_WINDOW} every {FRAME_EVERY_S} s",
            exit_status=None,
            source="user",
        )
        now = self._clock()
        self._state = FrameState(
            running=True,
            started_at=now,
            ends_at=now + timedelta(seconds=self._limit_s),
            fcs_reported=fcs,
        )
        self._task = asyncio.get_running_loop().create_task(self._loop(rec, t, phy, own))
        return self._state

    async def stop(self, reason: str | None = None) -> FrameState:
        task = self._task
        if task is not None and not task.done():
            if not self._stopping:  # a second Stop must not cancel the first one's cleanup
                self._stopping = True
                self._state = replace(self._state, error=reason)
                task.cancel()
            await asyncio.wait({task})  # never cancels the loop, even when this caller is cancelled
        return self._state

    # ---------------------------------------------------------------- the windows
    async def _loop(self, rec: RouterRecord, t: Transport, phy: str, own: set[str]) -> None:
        run = self._run_fn(rec, t)
        parked = failures = 0
        try:
            while True:
                why = self._why_stop(parked, failures)
                if why is not None:
                    self._state = replace(self._state, error=why)
                    return
                try:
                    up = (
                        (await ubus_call(t, "network.wireless", "status") or {}).get(self.radio, {}).get("up")
                    )
                    parked = 0 if up else parked + 1
                    if up:
                        await self._keep_monitor(rec.id, phy, t, run)
                    result = await t.run(FRAME_WINDOW, timeout=10.0)
                    failures = 0
                except GuardLocked:  # a run started between the check and the monitor's add: stop next round
                    continue
                except TransportError as exc:
                    failures += 1
                    log.info("frame window on %s failed: %s", rec.id, exc)
                    await self._sleep(FRAME_EVERY_S - FRAME_WINDOW_S)
                    continue
                except ValueError as exc:  # the monitor could not be added again
                    self._state = replace(self._state, error=f"No monitor interface: {exc}")
                    return
                if up:
                    self._window(summarize(result.stdout, result.stderr, own, FRAME_WINDOW_S))
                await self._sleep(FRAME_EVERY_S - FRAME_WINDOW_S)
        finally:
            await self._finish(rec, t, run)

    async def _keep_monitor(
        self, router_id: str, phy: str, t: Transport, run: Callable[[str, bool], Awaitable[CommandResult]]
    ) -> None:
        """After a Wi-Fi reload: the monitor back, and its flags set again whoever added it (an Apply's
        beacon check may have). Both are writes, so they wait for an Apply that holds the router."""
        async with self._pool.write_lock(router_id):
            await self._monitors.ensure(router_id, phy, t, run)
            if self._monitors.generation(router_id) != self._flags_at:
                await run(MONITOR_FLAGS, True)
                self._flags_at = self._monitors.generation(router_id)
                self._state = replace(self._state, note=REDONE)

    def _why_stop(self, parked: int, failures: int) -> str | None:
        guard = self._guard.state()
        if guard.live:
            return f"Bench Guard: {guard.reasons[0].text if guard.reasons else 'a harness run started'}"
        if self._state.ends_at is not None and self._clock() >= self._state.ends_at:
            return LIMIT
        if parked >= PARKED_WINDOWS:
            return f"{self.radio} is parked: nothing of its own to analyse"
        if failures >= FAILURES:
            return "The router stopped answering"
        return None

    def _window(self, window: FrameWindow) -> None:
        totals = window if self._state.totals is None else combine(self._state.totals, window)
        self._state = replace(self._state, windows=self._state.windows + 1, last=window, totals=totals)
        self._publish({"type": "frames", "state": self._state})

    async def _finish(
        self, rec: RouterRecord, t: Transport, run: Callable[[str, bool], Awaitable[Any]]
    ) -> None:
        """Let go of the monitor (the last holder removes it, also during a run) and say it stopped."""
        try:
            with contextlib.suppress(TransportError):
                async with self._pool.write_lock(rec.id):
                    await self._monitors.release(rec.id, self._holder, run)
        finally:
            self._state = replace(self._state, running=False)
            self._publish({"type": "frames", "state": self._state})
