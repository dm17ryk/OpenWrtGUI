"""A transport for tests on real routers that refuses every command that could change the router."""

from __future__ import annotations

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.probe import commands
from openwrtgui.transport.base import CommandResult, ShellChannel, Transport

# The probes' fixed command strings. Two of them (the LuCI menu and ACL loops) only read but are shell
# loops, which the terminal's read-only check rejects on principle; exact matches are allowed here.
PROBE_COMMANDS = frozenset(v for k, v in vars(commands).items() if k.isupper() and isinstance(v, str))


class ReadOnlyTransport:
    """Wraps a transport; runs only probe commands and commands `is_read_only_command` accepts."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner
        self.commands: list[str] = []

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if command not in PROBE_COMMANDS and not is_read_only_command(command):
            raise AssertionError(f"refusing a command that is not read-only: {command}")
        self.commands.append(command)
        return await self._inner.run(command, timeout=timeout)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        raise AssertionError(f"refusing a command with stdin on a real router: {command}")

    async def open_shell(self, cols: int, rows: int) -> ShellChannel:
        raise AssertionError("refusing to open a shell on a real router")

    async def close(self) -> None:
        await self._inner.close()
