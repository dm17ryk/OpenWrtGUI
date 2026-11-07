"""A transport for tests on real routers that refuses every command that could change the router."""

from __future__ import annotations

import re

from openwrtgui.guard.readonly import is_read_only_command
from openwrtgui.probe import commands
from openwrtgui.transport.base import CommandResult, Forwarder, LocalForward, ShellChannel, Transport

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


AP2 = "192.168.1.2"


def write_refusal(router: str, *, allow_writes: bool, txctl_told: bool) -> str | None:
    """Why a test that changes the router may not run, or None. Only AP2, and only when both flags say so."""
    if router != AP2:
        return f"tests that change a router run on AP2 ({AP2}) only, not {router}"
    if not allow_writes:
        return "pass --allow-writes: this test changes AP2 (its Wi-Fi or its network) and restores it"
    if not txctl_told:
        return (
            "pass --txctl-told once the txctl session has been told of the window on AP2 "
            "(a radio-on window, a network window: lan briefly at 192.168.1.12, or a firewall and faults "
            "window: fw4 reloads)"
        )
    return None


# rpcd sessions live in memory and change no config: one `ubus call session …` with one quoted JSON argument.
_SESSION_CALL = re.compile(r"ubus call session (create|grant|set|destroy|list) '[^']*'")


class LuciSessionTransport(ReadOnlyTransport):
    """Read-only, plus the LuCI bridge's rpcd session calls and its SSH forward to the router's web server."""

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        if _SESSION_CALL.fullmatch(command):
            self.commands.append(command)
            return await self._inner.run(command, timeout=timeout)
        return await super().run(command, timeout=timeout)

    async def forward_local(self, remote_host: str, remote_port: int) -> LocalForward:
        if not isinstance(self._inner, Forwarder):
            raise AssertionError("this connection cannot forward a port")
        return await self._inner.forward_local(remote_host, remote_port)
