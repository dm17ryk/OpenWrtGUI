"""Tool sessions (v1.2b R2, R3): a router tool (iperf3, socat's Listen) that runs for a while and streams
its output back. It runs on its own SSH connection, as a capture does, so a firewall apply that reconnects the
pooled one does not end it. Its command prints its own pid first and `exec`s the tool under BusyBox
`timeout -s KILL`, which keeps the pid: Stop sends `kill <pid>` over the pooled connection. Bench Guard going
live, the time limit and the router going away each end a session once, with one clear error or none."""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import hashlib
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import ByteStream, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

SCREEN = "Tools"
NOTES_KEPT = 20
LIMIT_EXIT = 137  # timeout -s KILL ended the tool at its limit: the session's normal end
_PID = re.compile(r"OWG-PID (\d+)")

SessionKind = Literal["throughput", "listen"]


def session_command(limit_s: int, program: str) -> str:
    """The command a session runs: its pid first, then the tool itself in the same process."""
    return f'echo "OWG-PID $$"; exec timeout -s KILL {limit_s} {program} 2>&1'


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Interval(_Frozen):
    start_s: float
    end_s: float
    mbps: float
    retransmits: int | None = None
    jitter_ms: float | None = None
    lost_pct: float | None = None


class ThroughputSummary(_Frozen):
    sent_mbps: float | None = None
    received_mbps: float | None = None
    jitter_ms: float | None = None
    lost_pct: float | None = None
    cpu_pct: float | None = None
    retransmits: int | None = None


class Peer(_Frozen):
    address: str
    port: int
    bytes: int
    first_hex: str  # at most 128 hex characters: the first 64 bytes


class SessionView(_Frozen):
    id: str
    router_id: str
    kind: SessionKind
    title: str
    command: str
    started_at: float
    ends_at: float
    running: bool
    intervals: list[Interval] = []
    summary: ThroughputSummary | None = None
    peers: list[Peer] = []
    notes: list[str] = []  # the last NOTES_KEPT
    error: str | None = None


LineParser = Callable[[SessionView, str], SessionView]


def add_note(view: SessionView, text: str) -> SessionView:
    return view.model_copy(update={"notes": [*view.notes, text][-NOTES_KEPT:]})


class ToolPlan(_Frozen):
    lines: list[str]
    warnings: list[str]
    digest: str


def tool_plan(lines: list[str], warnings: list[str]) -> ToolPlan:
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
    return ToolPlan(lines=lines, warnings=warnings, digest=digest)


async def _close(t: Transport) -> None:
    """Close a session's own connection; one already gone is closed."""
    with contextlib.suppress(TransportError, OSError):
        await t.close()


class ToolSessions:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        clock: Callable[[], float] = time.time,
        guard_poll_s: float = 1.0,
        grace_s: float = 10.0,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._clock = clock
        self._guard_poll_s = guard_poll_s
        self._grace_s = grace_s
        self._views: dict[str, SessionView] = {}
        self._streams: dict[str, ByteStream] = {}  # while the stream is open
        self._pids: dict[str, int] = {}
        self._pumps: dict[str, asyncio.Task[None]] = {}
        self._halted: set[str] = set()  # the first stop is under way or done: later ones send nothing
        self._running: dict[str, str] = {}  # router id -> session id ("" while it starts)
        self._tasks: set[asyncio.Task[None]] = set()

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    def _name(self, router_id: str) -> str:
        rec = self._routers.get(router_id)
        return rec.name if rec else router_id

    # ---------------------------------------------------------------- reads
    def get(self, session_id: str) -> SessionView:
        view = self._views.get(session_id)
        if view is None:
            raise ValueError(f"No tool session {session_id}")
        return view

    def list(self, router_id: str) -> builtins.list[SessionView]:
        return sorted(
            (v for v in self._views.values() if v.router_id == router_id), key=lambda v: v.started_at
        )

    def live(self) -> builtins.list[str]:
        """The sessions running now, for the update's question (spec 9.3)."""
        return [f"{v.title} on {self._name(v.router_id)}" for v in self._views.values() if v.running]

    def running_on(self, router_id: str) -> str | None:
        """What session holds the router now, for Remove from the app; None when none does."""
        if router_id not in self._running:
            return None
        view = self._views.get(self._running[router_id])
        return f"{view.title.lower()} runs" if view is not None else "a tool session is starting"

    # ---------------------------------------------------------------- start
    async def start(
        self, router_id: str, *, kind: SessionKind, title: str, command: str, limit_s: int, parse: LineParser
    ) -> SessionView:
        rec = self._record(router_id)
        if router_id in self._running:
            held = self._views.get(self._running[router_id])
            raise RouterBusy(f"{held.title if held else 'A tool session'} runs on {rec.name}: stop it first.")
        self._guard.require_clear()
        self._running[router_id] = ""  # taken before any await: one session per router
        try:
            return await self._start(rec, kind, title, command, limit_s, parse)
        except BaseException:
            self._running.pop(router_id, None)
            raise

    async def _start(
        self, rec: RouterRecord, kind: SessionKind, title: str, command: str, limit_s: int, parse: LineParser
    ) -> SessionView:
        # its own connection: an apply with rollback reconnects the pooled one, which would end the stream
        own = await self._pool.fresh(rec)
        try:
            stream = await own.stream(command)  # type: ignore[attr-defined]
        except BaseException:
            await _close(own)
            raise
        self._audit.record(router=rec.id, screen=SCREEN, command=command, exit_status=None, source="user")
        now = self._clock()
        view = SessionView(
            id=secrets.token_hex(4),
            router_id=rec.id,
            kind=kind,
            title=title,
            command=command,
            started_at=now,
            ends_at=now + limit_s,
            running=True,
        )
        self._views[view.id] = view
        self._streams[view.id] = stream
        self._running[rec.id] = view.id
        pump = asyncio.create_task(self._pump(rec, own, view.id, stream, parse))
        self._pumps[view.id] = pump
        watcher = asyncio.create_task(self._watch(view.id))
        for task in (pump, watcher):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return view

    # ---------------------------------------------------------------- the stream
    def _line(self, session_id: str, line: str, parse: LineParser) -> None:
        if session_id not in self._pids and (m := _PID.fullmatch(line)):
            self._pids[session_id] = int(m.group(1))
            return
        self._views[session_id] = parse(self._views[session_id], line)

    async def _pump(
        self, rec: RouterRecord, own: Transport, session_id: str, stream: ByteStream, parse: LineParser
    ) -> None:
        buf = b""
        error: str | None = None
        try:
            while chunk := await stream.read(65536):
                *lines, buf = (buf + chunk).split(b"\n")
                for raw in lines:
                    self._line(session_id, raw.decode(errors="replace").rstrip("\r"), parse)
                    if self._views[session_id].error is not None and session_id not in self._halted:
                        await self._halt(
                            session_id, None
                        )  # the parser saw the tool fail: end it on the router
            if buf:
                self._line(session_id, buf.decode(errors="replace").rstrip("\r"), parse)
        except (TransportError, OSError) as exc:
            if session_id not in self._halted:
                error = f"The router stopped answering: {exc}"
        finally:
            self._streams.pop(session_id, None)
            with contextlib.suppress(TransportError, OSError):
                await stream.close()
            await _close(own)
            self._audit.record(
                router=rec.id,
                screen=SCREEN,
                command="session ended",
                exit_status=stream.exit_status,
                source="app",
            )
            self._finish(rec.id, session_id, error, stream.exit_status)

    def _finish(self, router_id: str, session_id: str, error: str | None, status: int | None) -> None:
        view = self._views[session_id]
        asked = session_id in self._halted
        if view.error is None and error is None and not asked and status not in (0, LIMIT_EXIT, None):
            # Ruling (Task 1): a tool that failed on its own says why, from its last line
            error = view.notes[-1] if view.notes else f"exit {status}"
        self._views[session_id] = view.model_copy(
            update={"running": False, "error": view.error if view.error is not None else error}
        )
        if self._running.get(router_id) == session_id:
            del self._running[router_id]

    async def _watch(self, session_id: str) -> None:
        """Every guard_poll_s: a live Bench Guard, or a router that did not end the tool at its limit, stops
        it."""
        while self._views[session_id].running:
            await asyncio.sleep(self._guard_poll_s)
            view = self._views[session_id]
            if not view.running or session_id in self._halted:
                return
            state = self._guard.state()
            if state.live:
                text = state.reasons[0].text if state.reasons else "a harness run"
                await self.stop(session_id, f"Stopped by Bench Guard: {text}")
            elif self._clock() >= view.ends_at + self._grace_s:
                await self.stop(session_id, "Stopped: the router did not end it at its limit")

    # ---------------------------------------------------------------- stop
    async def _halt(self, session_id: str, reason: str | None) -> None:
        """The one stop path: `kill <pid>` when the pid is known and the stream is open, then close the
        stream. The kill is allowed during a run (it only ends what the app started)."""
        if session_id in self._halted:
            return
        self._halted.add(session_id)
        view = self._views[session_id]
        if reason is not None and view.error is None:
            self._views[session_id] = view = view.model_copy(update={"error": reason})
        stream = self._streams.get(session_id)
        if stream is None:
            return
        pid = self._pids.get(session_id)
        if pid is not None:
            rec = self._record(view.router_id)
            try:
                t = await self._pool.get(rec)
                await run_audited(
                    t,
                    f"kill {pid}",
                    router_id=rec.id,
                    screen=SCREEN,
                    guard=self._guard,
                    audit=self._audit,
                    source="app",
                    require_guard=False,
                )
            except TransportError as exc:
                ends = datetime.fromtimestamp(view.ends_at).strftime("%H:%M:%S")
                note = f"Could not stop it on the router: {exc}; it ends by itself at {ends}"
                self._views[session_id] = add_note(self._views[session_id], note)
        with contextlib.suppress(TransportError, OSError):
            await stream.close()

    async def stop(self, session_id: str, reason: str | None = None) -> SessionView:
        self.get(session_id)
        await self._halt(session_id, reason)
        pump = self._pumps.get(session_id)
        if pump is not None and not pump.done():
            await asyncio.wait({pump})  # never cancels the pump, even when this caller is cancelled
        return self._views[session_id]

    async def stop_all(self) -> None:
        for view in builtins.list(self._views.values()):
            if view.running:
                await self.stop(view.id)
