"""Every change to a router goes through here: guard check, write lock, audit."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from openwrtgui.guard.audit import AuditLog, Source, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.transport.base import CommandResult, Transport


@dataclass(frozen=True)
class WriteAction:
    router_id: str
    screen: str
    commands: tuple[str, ...]
    secrets: tuple[str, ...] = ()
    stdin: str | None = None

    def preview(self) -> list[str]:
        return [mask(c, self.secrets) for c in self.commands]


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
            if action.stdin is not None:
                result = await transport.run_stdin(command, action.stdin)
            else:
                result = await transport.run(command)
            audit.record(
                router=action.router_id,
                screen=action.screen,
                command=command,
                exit_status=result.exit_status,
                source=source,
                secrets=action.secrets,
            )
            results.append(result)
            if not result.ok:
                break
    return results
