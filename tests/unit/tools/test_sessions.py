"""Tool sessions (v1.2b R2, R3): a router tool streams on its own connection; Stop, Bench Guard, the limit
and a router that goes away each end it once, with one clear error or none."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.audit import AuditEntry, AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked, ProcessInfo
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.tools.sessions import SessionView, ToolSessions, add_note, session_command
from openwrtgui.transport.base import CommandResult, TransportError

RUN = ProcessInfo(18244, ("python.exe", "dima_night.py"), datetime(2026, 11, 20, 21, 4))
COMMAND = session_command(70, "iperf3 -s")


class HeldStream:
    """A router tool's output, fed by the test through a queue; b"" is the end."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes | Exception] = asyncio.Queue()
        self.exit_status: int | None = None
        self.stderr = ""
        self.closed = False

    def feed(self, *lines: str) -> None:
        for line in lines:
            self.queue.put_nowait(f"{line}\n".encode())

    def end(self, status: int) -> None:
        self.exit_status = status
        self.queue.put_nowait(b"")

    async def read(self, n: int = 65536) -> bytes:
        if self.closed and self.queue.empty():
            return b""
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True
        self.queue.put_nowait(b"")


class OwnTransport:
    def __init__(self, stream: HeldStream) -> None:
        self.held = stream
        self.streamed: list[str] = []
        self.closed = False

    async def stream(self, command: str) -> HeldStream:
        self.streamed.append(command)
        return self.held

    async def close(self) -> None:
        self.closed = True


class PooledTransport:
    def __init__(self) -> None:
        self.ran: list[str] = []
        self.fail: Exception | None = None

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.ran.append(command)
        if self.fail is not None:
            raise self.fail
        return CommandResult(command, "", "", 0)

    async def stream(self, command: str) -> HeldStream:
        raise AssertionError("a session never streams on the pooled connection")


class StubPool:
    def __init__(self) -> None:
        self.held = HeldStream()
        self.own: list[OwnTransport] = []
        self.pooled = PooledTransport()

    async def fresh(self, rec: RouterRecord) -> OwnTransport:
        own = OwnTransport(self.held)
        self.own.append(own)
        return own

    async def get(self, rec: RouterRecord) -> PooledTransport:
        return self.pooled


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.routers = RouterStore(tmp_path / "routers.json")
        self.routers.upsert(
            RouterRecord(
                id="ap2", name="AP2", host="192.168.1.2", auth="key", added_at=datetime(2026, 11, 20)
            )
        )
        self.processes: list[ProcessInfo] = []
        self.guard = BenchGuard(
            GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: self.processes
        )
        self.guard.check_local()
        self.audit = AuditLog(tmp_path / "audit")
        self.pool = StubPool()
        self.now = 1_000_000.0
        self.sessions = ToolSessions(
            pool=self.pool,  # type: ignore[arg-type]
            routers=self.routers,
            guard=self.guard,
            audit=self.audit,
            clock=lambda: self.now,
            guard_poll_s=0.01,
            grace_s=10.0,
        )

    def go_live(self) -> None:
        self.processes.append(RUN)
        self.guard.check_local()

    def entries(self) -> list[AuditEntry]:
        return list(reversed(self.audit.query()))

    async def start(self, title: str = "Throughput") -> SessionView:
        return await self.sessions.start(
            "ap2", kind="throughput", title=title, command=COMMAND, limit_s=70, parse=_notes
        )

    async def ended(self, session_id: str) -> SessionView:
        for _ in range(500):
            view = self.sessions.get(session_id)
            if not view.running:
                return view
            await asyncio.sleep(0.01)
        raise AssertionError("the session did not end")


def _notes(view: SessionView, line: str) -> SessionView:
    return add_note(view, line)


def _fails(view: SessionView, line: str) -> SessionView:
    return view.model_copy(update={"error": "x"})


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_session_command() -> None:
    assert session_command(70, "iperf3 -s") == 'echo "OWG-PID $$"; exec timeout -s KILL 70 iperf3 -s 2>&1'


async def test_start_streams_on_its_own_connection_and_audits(env: Env) -> None:
    view = await env.start()
    assert view.running and view.kind == "throughput" and view.title == "Throughput"
    assert view.ends_at == view.started_at + 70
    env.pool.held.feed("OWG-PID 4242", "a", "b")
    env.pool.held.end(0)
    done = await env.ended(view.id)
    assert done.notes == ["a", "b"] and done.running is False and done.error is None
    assert [own.streamed for own in env.pool.own] == [[COMMAND]] and env.pool.own[0].closed
    assert env.pool.pooled.ran == []
    entries = env.entries()
    assert (entries[0].command, entries[0].source, entries[0].screen) == (COMMAND, "user", "Tools")
    assert (entries[-1].command, entries[-1].exit_status, entries[-1].source) == ("session ended", 0, "app")


async def test_one_session_per_router(env: Env) -> None:
    await env.start()
    with pytest.raises(RouterBusy, match=r"^Throughput runs on AP2: stop it first\.$"):
        await env.start("Traffic listen")
    assert len(env.pool.own) == 1


async def test_refused_while_bench_guard_is_live(env: Env) -> None:
    env.go_live()
    with pytest.raises(GuardLocked):
        await env.start()
    assert env.pool.own == [] and env.sessions.list("ap2") == []
    assert env.sessions.running_on("ap2") is None


async def test_stop_kills_the_pid(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242")
    await asyncio.sleep(0.05)
    stopped = await env.sessions.stop(view.id)
    assert stopped.running is False and stopped.error is None
    assert env.pool.pooled.ran == ["kill 4242"]
    kill = next(e for e in env.entries() if e.command == "kill 4242")
    assert kill.source == "app"
    again = await env.sessions.stop(view.id)
    assert again.running is False and env.pool.pooled.ran == ["kill 4242"]


async def test_bench_guard_stops_it(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242")
    await asyncio.sleep(0.05)
    env.go_live()
    done = await env.ended(view.id)
    assert done.error == "Stopped by Bench Guard: dima_night.py started 21:04 (PID 18244)"
    assert env.pool.pooled.ran == ["kill 4242"]


async def test_router_drop_ends_it(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242")
    env.pool.held.queue.put_nowait(TransportError("gone"))
    done = await env.ended(view.id)
    assert done.error == "The router stopped answering: gone"
    assert env.pool.pooled.ran == []


async def test_limit_end_is_no_error(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242", "a")
    env.pool.held.end(137)
    done = await env.ended(view.id)
    assert done.error is None and done.notes == ["a"]
    assert env.pool.pooled.ran == []


async def test_a_failed_tool_says_why(env: Env) -> None:
    """Ruling (Task 1): a tool that fails on its own, unasked, shows its last line as the error."""
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242", "socat[77] E bind(5, ...): Address in use")
    env.pool.held.end(1)
    done = await env.ended(view.id)
    assert done.error == "socat[77] E bind(5, ...): Address in use"


async def test_no_answer_after_the_limit_is_stopped(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242")
    await asyncio.sleep(0.05)
    env.now += 70 + 10
    done = await env.ended(view.id)
    assert done.error == "Stopped: the router did not end it at its limit"
    assert env.pool.pooled.ran == ["kill 4242"]


async def test_parser_error_stops_it(env: Env) -> None:
    view = await env.sessions.start(
        "ap2", kind="throughput", title="Throughput", command=COMMAND, limit_s=70, parse=_fails
    )
    env.pool.held.feed("OWG-PID 4242", "anything")
    done = await env.ended(view.id)
    assert done.error == "x" and env.pool.pooled.ran == ["kill 4242"]


async def test_failed_kill_is_a_note(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242")
    await asyncio.sleep(0.05)
    env.pool.pooled.fail = TransportError("no route")
    stopped = await env.sessions.stop(view.id)
    ends = datetime.fromtimestamp(view.ends_at).strftime("%H:%M:%S")
    assert stopped.notes[-1] == f"Could not stop it on the router: no route; it ends by itself at {ends}"
    assert stopped.running is False


async def test_notes_keep_the_last_20(env: Env) -> None:
    view = await env.start()
    env.pool.held.feed("OWG-PID 4242", *(f"line {i}" for i in range(25)))
    env.pool.held.end(0)
    done = await env.ended(view.id)
    assert done.notes == [f"line {i}" for i in range(5, 25)]


async def test_live_running_on_stop_all(env: Env) -> None:
    assert env.sessions.live() == [] and env.sessions.running_on("ap2") is None
    view = await env.start()
    assert env.sessions.live() == ["Throughput on AP2"]
    assert env.sessions.running_on("ap2") == "throughput runs"
    assert [v.id for v in env.sessions.list("ap2")] == [view.id]
    env.pool.held.feed("OWG-PID 4242")
    await asyncio.sleep(0.05)
    await env.sessions.stop_all()
    assert env.sessions.live() == [] and env.sessions.running_on("ap2") is None
    assert not env.sessions.get(view.id).running


async def test_traffic_listen_running_on(env: Env) -> None:
    await env.start("Traffic listen")
    assert env.sessions.running_on("ap2") == "traffic listen runs"


def test_unknown_session(env: Env) -> None:
    with pytest.raises(ValueError, match="^No tool session nope$"):
        env.sessions.get("nope")
