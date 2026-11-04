from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, ProcessInfo
from openwrtgui.store.routers import RouterRecord
from openwrtgui.store.settings import GuardWatchList
from openwrtgui.terminal import TerminalMode, TerminalSession, refusal_message
from openwrtgui.transport.base import CommandResult, ShellChannel, Transport
from openwrtgui.transport.fake import ReplayTransport
from openwrtgui.transport.pool import ConnectionPool

REC = RouterRecord(id="ap2", name="AP2", host="192.168.1.2", auth="key", added_at=datetime(2026, 11, 3))


class FakeShell:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.closed = False
        self._out: asyncio.Queue[str] = asyncio.Queue()

    async def write(self, data: str) -> None:
        self.written.append(data)

    async def read(self) -> str:
        return await self._out.get()

    async def resize(self, cols: int, rows: int) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
        self._out.put_nowait("")


class ShellTransport(ReplayTransport):
    def __init__(self, shell: FakeShell) -> None:
        super().__init__({"uname -a": CommandResult("uname -a", "Linux AP2\n", "", 0)})
        self.shell = shell

    async def open_shell(self, cols: int, rows: int) -> ShellChannel:
        return self.shell


class Guard:
    def __init__(self) -> None:
        self.procs: list[ProcessInfo] = []
        self.guard = BenchGuard(
            GuardWatchList(lock_files=[], processes=["dima_night.py"]), lister=lambda: self.procs
        )
        self.guard.check_local()

    def go_live(self) -> None:
        self.procs.append(ProcessInfo(18244, ("dima_night.py",), datetime(2026, 11, 3, 21, 4)))
        self.guard.check_local()


async def _open(
    transport: Transport, guard: BenchGuard, audit: AuditLog
) -> tuple[TerminalSession, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    async def emit(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def factory(rec: RouterRecord) -> Transport:
        return transport

    session = await TerminalSession.open(
        REC, pool=ConnectionPool(factory), guard=guard, audit=audit, emit=emit
    )
    return session, sent


async def test_line_mode_refuses_writes_during_run(tmp_path: Path) -> None:
    g = Guard()
    g.go_live()
    t = ReplayTransport({})
    session, sent = await _open(t, g.guard, AuditLog(tmp_path))
    assert session.mode == TerminalMode.LINE
    await session.run_line("reboot")
    refused = [m for m in sent if m["type"] == "refused"]
    assert refused == [{"type": "refused", "line": "reboot", "reason": refusal_message(g.guard.state())}]
    assert refusal_message(g.guard.state()) == (
        "Refused while dima_night.py started 21:04 (PID 18244): "
        "only read-only commands run during a harness run."
    )
    assert t.calls == []


async def test_line_mode_runs_read_only_and_audits(tmp_path: Path) -> None:
    g = Guard()
    g.go_live()
    audit = AuditLog(tmp_path)
    t = ReplayTransport({"uname -a": CommandResult("uname -a", "Linux AP2\n", "", 0)})
    session, sent = await _open(t, g.guard, audit)
    await session.run_line("uname -a")
    assert {"type": "output", "data": "Linux AP2\r\n"} in sent
    assert sent[-1] == {"type": "exit", "status": 0}
    entries = audit.query()
    assert [(e.command, e.source, e.router, e.screen) for e in entries] == [
        ("uname -a", "terminal", "ap2", "Terminal")
    ]


async def test_guard_going_live_closes_pty_and_switches_to_line_mode(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    session, sent = await _open(ShellTransport(shell), g.guard, AuditLog(tmp_path))
    assert session.mode == TerminalMode.PTY
    g.go_live()
    await session.on_guard(g.guard.state())
    assert shell.closed and session.mode == TerminalMode.LINE
    assert {
        "type": "output",
        "data": "\r\n[Harness run started: terminal switched to read-only line mode]\r\n",
    } in sent
    mode_msgs = [m for m in sent if m["type"] == "mode"]
    assert mode_msgs[-1]["mode"] == "line" and "dima_night.py" in mode_msgs[-1]["reason"]
    await session.close()


async def test_pty_input_checks_the_guard_itself(tmp_path: Path) -> None:
    """A missed guard message must not leave a full shell open during a run."""
    g = Guard()
    shell = FakeShell()
    session, sent = await _open(ShellTransport(shell), g.guard, AuditLog(tmp_path))
    g.go_live()  # live, but on_guard was never called
    await session.input("reboot\r")
    assert shell.written == []
    assert shell.closed and session.mode == TerminalMode.LINE
    assert [m for m in sent if m["type"] == "mode"][-1]["mode"] == "line"
    await session.input("x")  # stray keystrokes after the switch are ignored, not an error
    await session.close()


async def test_guard_clear_offers_pty_again(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    session, sent = await _open(ShellTransport(shell), g.guard, AuditLog(tmp_path))
    g.go_live()
    await session.on_guard(g.guard.state())
    g.procs.clear()
    await session.on_guard(g.guard.check_local())
    assert sent[-1] == {"type": "mode", "mode": "line-available-pty", "reason": None}
    await session.close()


async def test_pty_input_lines_audited_without_control_chars(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    audit = AuditLog(tmp_path)
    session, _ = await _open(ShellTransport(shell), g.guard, audit)
    await session.input("lx\x7fs\x1b[A\r")
    assert shell.written == ["lx\x7fs\x1b[A\r"]
    assert [e.command for e in audit.query()] == ["ls"]
    await session.close()


async def _until_output(sent: list[dict[str, Any]], text: str) -> None:
    for _ in range(50):
        if any(text in m.get("data", "") for m in sent):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"no output containing {text!r}")


def _audit_text(tmp_path: Path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.jsonl"))


async def test_pty_input_at_a_password_prompt_is_not_audited(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    audit = AuditLog(tmp_path)
    session, sent = await _open(ShellTransport(shell), g.guard, audit)
    await session.input("passwd\r")
    shell._out.put_nowait("passwd\r\nChanging password for root\r\nNew password: ")
    await _until_output(sent, "New password: ")
    await session.input("s3cret!\r")
    shell._out.put_nowait("\r\nRetype password: ")
    await _until_output(sent, "Retype password: ")
    await session.input("s3cret!\r")
    shell._out.put_nowait("\r\npasswd: password for root changed by root\r\nroot@AP2:~# ")
    await _until_output(sent, "root@AP2:~# ")
    await session.input("uptime\r")
    assert [e.command for e in audit.query()] == ["uptime", "<hidden>", "<hidden>", "passwd"]
    assert "s3cret!" not in _audit_text(tmp_path)
    await session.close()


async def test_pty_paste_ahead_after_passwd_is_not_audited(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    audit = AuditLog(tmp_path)
    session, _ = await _open(ShellTransport(shell), g.guard, audit)
    await session.input("passwd root\rs3cret!\rs3cret!\r")
    assert [e.command for e in audit.query()] == ["<hidden>", "<hidden>", "passwd root"]
    assert "s3cret!" not in _audit_text(tmp_path)
    await session.close()


async def test_pty_output_is_forwarded(tmp_path: Path) -> None:
    g = Guard()
    shell = FakeShell()
    session, sent = await _open(ShellTransport(shell), g.guard, AuditLog(tmp_path))
    shell._out.put_nowait("root@AP2:~# ")
    for _ in range(20):
        if {"type": "output", "data": "root@AP2:~# "} in sent:
            break
        await asyncio.sleep(0.01)
    assert {"type": "output", "data": "root@AP2:~# "} in sent
    await session.close()
