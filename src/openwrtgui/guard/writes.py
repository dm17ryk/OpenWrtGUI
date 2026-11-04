"""Every change to a router goes through here: guard check, write lock, audit."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from openwrtgui.guard.audit import AuditLog, Source, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.transport.base import CommandResult, Transport, TransportError


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
) -> CommandResult:
    """One command: refused while Bench Guard is live, audited masked. The caller holds the write lock."""
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
