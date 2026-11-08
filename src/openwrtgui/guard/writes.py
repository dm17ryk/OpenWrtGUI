"""Every change to a router goes through here: guard check, write lock, audit."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from openwrtgui.guard.audit import AuditLog, Source, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.transport.base import CommandResult, Transport, TransportError, Uploader


@dataclass(frozen=True)
class WriteAction:
    router_id: str
    screen: str
    commands: tuple[str, ...]
    secrets: tuple[str, ...] = ()
    stdin: str | None = None

    def preview(self) -> list[str]:
        return [mask(c, self.secrets) for c in self.commands]


async def run_audited(
    transport: Transport,
    command: str,
    *,
    router_id: str,
    screen: str,
    guard: BenchGuard,
    audit: AuditLog,
    source: Source = "user",
    secrets: Sequence[str] = (),
    stdin: str | None = None,
    timeout: float = 15.0,
    require_guard: bool = True,
) -> CommandResult:
    """One command: refused while Bench Guard is live, audited masked. The caller holds the write lock.

    require_guard=False is for commands that change no router config (rpcd sessions in memory)."""
    if require_guard:
        guard.require_clear()
    try:
        if stdin is not None:
            result = await transport.run_stdin(command, stdin, timeout=timeout)
        else:
            result = await transport.run(command, timeout=timeout)
    except TransportError:
        audit.record(
            router=router_id, screen=screen, command=command, exit_status=None, source=source, secrets=secrets
        )
        raise
    audit.record(
        router=router_id,
        screen=screen,
        command=command,
        exit_status=result.exit_status,
        source=source,
        secrets=secrets,
    )
    return result


def upload_line(command: str, name: str, data: bytes) -> str:
    """What the preview and the audit log show for an upload: the exact command and what goes to its stdin."""
    return f"{command}  # stdin: {name} ({len(data)} B, sha256 {hashlib.sha256(data).hexdigest()[:12]})"


async def run_audited_upload(
    transport: Transport,
    command: str,
    data: bytes,
    *,
    name: str,
    router_id: str,
    screen: str,
    guard: BenchGuard,
    audit: AuditLog,
    source: Source = "user",
    progress: Callable[[int], None] | None = None,
    require_guard: bool = True,
    timeout: float = 600.0,
) -> CommandResult:
    """One upload, like run_audited: refused while Bench Guard is live, audited as upload_line. The caller
    holds the write lock."""
    if require_guard:
        guard.require_clear()
    if not isinstance(transport, Uploader):
        raise TransportError("This connection cannot send files")
    line = upload_line(command, name, data)
    try:
        result = await transport.upload(command, data, progress, timeout=timeout)
    except TransportError:
        audit.record(router=router_id, screen=screen, command=line, exit_status=None, source=source)
        raise
    audit.record(router=router_id, screen=screen, command=line, exit_status=result.exit_status, source=source)
    return result


async def perform_write(
    action: WriteAction,
    *,
    transport: Transport,
    lock: asyncio.Lock,
    guard: BenchGuard,
    audit: AuditLog,
    source: Source = "user",
) -> list[CommandResult]:
    guard.require_clear()
    if action.stdin is not None and len(action.commands) != 1:
        raise ValueError("stdin can only go with a single command")
    results: list[CommandResult] = []
    async with lock:
        for command in action.commands:
            result = await run_audited(
                transport,
                command,
                router_id=action.router_id,
                screen=action.screen,
                guard=guard,
                audit=audit,
                source=source,
                secrets=action.secrets,
                stdin=action.stdin,
            )
            results.append(result)
            if not result.ok:
                break
    return results
