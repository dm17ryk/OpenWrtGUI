"""Within one refresh, a read the router already answered is not asked again (v1.0c Task 6, D5).

A screen's refresh is a set of reads made one after the other within a second or so; asking the same read
twice in it only costs a round trip. The wrapper lives for one refresh, so the next refresh asks afresh."""

from __future__ import annotations

from openwrtgui.transport.base import CommandResult, ShellChannel, Transport


class OnceReads:
    """A Transport whose `run` answers a command it already ran with the first answer. A command that raised
    is not kept; commands fed input, shells and close pass through."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner
        self._answers: dict[str, CommandResult] = {}

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        kept = self._answers.get(command)
        if kept is not None:
            return kept
        answer = await self._inner.run(command, timeout=timeout)
        self._answers[command] = answer
        return answer

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        return await self._inner.run_stdin(command, stdin, timeout=timeout)

    async def open_shell(self, cols: int, rows: int) -> ShellChannel:
        return await self._inner.open_shell(cols, rows)

    async def close(self) -> None:
        await self._inner.close()


def once_reads(t: Transport) -> OnceReads:
    return OnceReads(t)
