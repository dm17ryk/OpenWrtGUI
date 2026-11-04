"""Terminal per router: a real shell normally, read-only line mode during a harness run."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from openwrtgui.guard.audit import HIDDEN, AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardState
from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import ShellChannel, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool

log = logging.getLogger(__name__)

SCREEN = "Terminal"
SWITCH_NOTICE = "\r\n[Harness run started: terminal switched to read-only line mode]\r\n"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_BACKSPACE = ("\x7f", "\x08")
# Lines typed at a prompt like this are secrets (input not echoed): audit them as <hidden>.
_SECRET_PROMPT = re.compile(r"(?i)(password|passphrase|\bpin\b|secret)[^\n]*:\s*$")
# Commands that ask for a secret: lines pasted after one in the same chunk are hidden too.
_ASKS_SECRET = re.compile(r"^(?:\S*/)?(?:passwd|chpasswd|su|ssh|dbclient|scp|sudo|htpasswd|login)\b")
_TAIL = 256

Emit = Callable[[dict[str, Any]], Awaitable[None]]


class TerminalMode(StrEnum):
    PTY = "pty"
    LINE = "line"


def refusal_message(state: GuardState) -> str:
    what = state.reasons[0].text if state.reasons else "a harness run"
    return f"Refused while {what}: only read-only commands run during a harness run."


def _clean_line(raw: str) -> str:
    text = _ANSI.sub("", raw)
    out: list[str] = []
    for ch in text:
        if ch in _BACKSPACE:
            if out:
                out.pop()
        elif ch >= " ":
            out.append(ch)
    return "".join(out).strip()


class TerminalSession:
    def __init__(
        self,
        router: RouterRecord,
        transport: Transport,
        guard: BenchGuard,
        audit: AuditLog,
        emit: Emit,
        shell: ShellChannel | None,
        pty_possible: bool,
    ) -> None:
        self.router = router
        self._transport = transport
        self._guard = guard
        self._audit = audit
        self._emit = emit
        self._shell = shell
        self._pty_possible = pty_possible
        self._buffer = ""
        self._tail = ""
        self._reader: asyncio.Task[None] | None = None

    @property
    def mode(self) -> TerminalMode:
        return TerminalMode.PTY if self._shell is not None else TerminalMode.LINE

    @classmethod
    async def open(
        cls,
        router: RouterRecord,
        *,
        pool: ConnectionPool,
        guard: BenchGuard,
        audit: AuditLog,
        emit: Emit,
        cols: int = 120,
        rows: int = 32,
    ) -> TerminalSession:
        transport = await pool.get(router)
        state = guard.state()
        shell: ShellChannel | None = None
        pty_possible = True
        if not state.live:
            try:
                shell = await transport.open_shell(cols, rows)
            except NotImplementedError:
                pty_possible = False
        session = cls(router, transport, guard, audit, emit, shell, pty_possible)
        if shell is not None:
            session._reader = asyncio.create_task(session._pump(shell))
        reason = refusal_message(state) if state.live else None
        await emit({"type": "mode", "mode": session.mode.value, "reason": reason})
        return session

    async def _pump(self, shell: ShellChannel) -> None:
        try:
            while True:
                data = await shell.read()
                if not data:
                    break
                self._tail = (self._tail + data)[-_TAIL:]
                await self._emit({"type": "output", "data": data})
        except (TransportError, OSError):
            log.debug("terminal shell on %s ended", self.router.id, exc_info=True)

    def _record(self, command: str, exit_status: int | None) -> None:
        self._audit.record(
            router=self.router.id, screen=SCREEN, command=command, exit_status=exit_status, source="terminal"
        )

    async def input(self, data: str) -> None:
        state = self._guard.state()
        if state.live and self._shell is not None:
            # Checked on every keystroke, so a missed guard message cannot keep a shell open in a run.
            await self.on_guard(state)
        if self._shell is None:
            log.debug("terminal on %s is in line mode; dropped %d chars of input", self.router.id, len(data))
            return
        await self._shell.write(data)
        self._buffer += data
        hide_rest = False
        while "\r" in self._buffer or "\n" in self._buffer:
            cut = min(i for i in (self._buffer.find("\r"), self._buffer.find("\n")) if i >= 0)
            line, self._buffer = _clean_line(self._buffer[:cut]), self._buffer[cut + 1 :]
            if not line:
                continue
            at_prompt = _SECRET_PROMPT.search(_ANSI.sub("", self._tail)) is not None
            self._record(HIDDEN if hide_rest or at_prompt else line, None)
            hide_rest = hide_rest or at_prompt or _ASKS_SECRET.match(line) is not None

    async def run_line(self, line: str) -> None:
        if self._shell is not None:
            raise ValueError("The terminal has a shell; send input instead")
        line = line.strip()
        if not line:
            return
        state = self._guard.state()
        if state.live and not is_read_only_command(line):
            await self._emit({"type": "refused", "line": line, "reason": refusal_message(state)})
            return
        result = await self._transport.run(line, timeout=60.0)
        text = (result.stdout + result.stderr).replace("\r\n", "\n").replace("\n", "\r\n")
        if text:
            await self._emit({"type": "output", "data": text})
        await self._emit({"type": "exit", "status": result.exit_status})
        self._record(line, result.exit_status)

    async def resize(self, cols: int, rows: int) -> None:
        if self._shell is not None:
            await self._shell.resize(cols, rows)

    async def _close_shell(self) -> None:
        shell, self._shell = self._shell, None
        if shell is not None:
            with contextlib.suppress(TransportError, OSError):
                await shell.close()
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None

    async def on_guard(self, state: GuardState) -> None:
        if state.live and self._shell is not None:
            await self._close_shell()
            await self._emit({"type": "output", "data": SWITCH_NOTICE})
            await self._emit({"type": "mode", "mode": "line", "reason": refusal_message(state)})
        elif not state.live and self._shell is None and self._pty_possible:
            await self._emit({"type": "mode", "mode": "line-available-pty", "reason": None})

    async def close(self) -> None:
        await self._close_shell()
