"""Replay transport: answers commands from recorded router output. Also the router simulator."""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from openwrtgui.transport.base import UPLOAD_CHUNK, CommandResult, ShellChannel, Unreachable

if TYPE_CHECKING:
    from openwrtgui.simaccess import SimAccess
    from openwrtgui.simair import SimAir
    from openwrtgui.simfiles import SimFiles
    from openwrtgui.simfw import SimFirewall
    from openwrtgui.simimage import SimImage
    from openwrtgui.simlater import SimLater
    from openwrtgui.simmodem import SimModem
    from openwrtgui.simnet import SimNetwork
    from openwrtgui.simsystem import SimSystem
    from openwrtgui.simtools import SimTools
    from openwrtgui.simwifi import SimWifi

INSTALL_KEY_PREFIX = "mkdir -p /etc/dropbear && "
REMOVE_KEY_PREFIX = "grep -qxF "  # the key rotation's removal of the old line (v1.1b)
ROOT_PASSWORD_PROBE = "/etc/shadow"


@dataclass
class SimState:
    """Mutable state of a simulated router (what writes change)."""

    authorized_keys: list[str] = field(default_factory=list)
    root_password: str | None = None
    password_login: str | None = None
    wifi: SimWifi | None = None
    net: SimNetwork | None = None
    fw: SimFirewall | None = None
    image: SimImage | None = None
    modem: SimModem | None = None
    system: SimSystem | None = None
    access: SimAccess | None = None  # v0.6c: dropbear, uhttpd, keys, LEDs, restore, reset
    generation_seen: int = 0  # the image's flash generation whose reset (keys, password) was applied
    key_seeded: bool = False  # v1.1b R8: a router added with a key trusts only its first login
    air: SimAir | None = None  # v0.7: scans, every channel's survey, frame windows (made with the Wi-Fi)
    files: SimFiles | None = None  # v1.0a1: what LuCI's menu asks about (ls -ldL, ls -A)
    later: SimLater | None = None  # v1.0a2: a later image's block-mount, iptables, plugins, menu entries
    tools: SimTools | None = None  # v1.2b: iperf3 and socat sessions, and the kill that stops them

    def __post_init__(self) -> None:
        if self.wifi is not None and self.air is None:
            from openwrtgui.simair import SimAir

            self.air = SimAir(self.wifi)


def load_commands(path: Path) -> dict[str, CommandResult]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        cmd: CommandResult(cmd, entry.get("stdout", ""), entry.get("stderr", ""), int(entry.get("exit", 0)))
        for cmd, entry in raw.items()
    }


class BytesStream:
    """A finished capture's bytes, read back in chunks (the simulator's tcpdump)."""

    def __init__(self, data: bytes, exit_status: int = 0, stderr: str = "") -> None:
        self._data = data
        self._closed = False
        self._final = (exit_status, stderr)
        self.exit_status: int | None = None
        self.stderr = ""

    async def read(self, n: int = 65536) -> bytes:
        if self._closed:
            return b""
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    async def close(self) -> None:
        self._closed = True
        self.exit_status, self.stderr = self._final


class LazyStream:
    """A stream whose bytes come from a callable at its first read (the simulator's `ubus subscribe`): one
    opened before a request still sees what the request makes. `timeout -s KILL` ends it."""

    def __init__(self, source: Callable[[], bytes], exit_status: int = 137) -> None:
        self._source = source
        self._data: bytes | None = None
        self._closed = False
        self._final = exit_status
        self.exit_status: int | None = None
        self.stderr = ""

    async def read(self, n: int = 65536) -> bytes:
        if self._closed:
            return b""
        if self._data is None:
            self._data = self._source()
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    async def close(self) -> None:
        self._closed = True
        self.exit_status = self._final


class ReplayTransport:
    def __init__(self, commands: Mapping[str, CommandResult], state: SimState | None = None) -> None:
        self._commands = dict(commands)
        self.state = state
        self.calls: list[str] = []
        self.uploads: dict[str, bytes] = {}  # command → the bytes it was fed, last upload wins

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        if self.state is not None:
            handled = self._simulate(command)
            if handled is not None:
                return handled
        recorded = self._commands.get(command)
        if recorded is not None:
            return recorded
        return CommandResult(command, "", f"sim: no recording for '{command}'", 127)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        self.calls.append(command)
        if command == "passwd root" and self.state is not None:
            lines = stdin.splitlines()
            if len(lines) >= 2 and lines[0] == lines[1] and lines[0]:
                self.state.root_password = lines[0]
                return CommandResult(command, "Password for root changed by root\n", "", 0)
            return CommandResult(command, "", "passwd: password for root is unchanged\n", 1)
        return await self.run(command, timeout=timeout)

    async def upload(
        self,
        command: str,
        data: bytes,
        progress: Callable[[int], None] | None = None,
        *,
        timeout: float = 600.0,
    ) -> CommandResult:
        """The simulated router takes it; without a simulator it is kept in `uploads` and succeeds."""
        self.calls.append(command)
        self._down()
        for at in range(0, len(data), UPLOAD_CHUNK):
            if progress is not None:
                progress(min(at + UPLOAD_CHUNK, len(data)))
        self.uploads[command] = data
        if self.state is not None and self.state.access is not None:
            taken = self.state.access.upload(command, data)
            if taken is not None:
                return taken
        if self.state is not None and self.state.image is not None:
            taken = self.state.image.upload(command, data)
            if taken is not None:
                return taken
            return CommandResult(command, "", f"sim: no upload target for '{command}'", 1)
        return CommandResult(command, "", "", 0)

    async def open_shell(self, cols: int, rows: int) -> ShellChannel:
        raise NotImplementedError("simulator has no shell")

    async def stream(self, command: str) -> BytesStream | LazyStream:
        self.calls.append(command)
        self._down()
        if self.state is not None and self.state.wifi is not None:
            subscribed = self.state.wifi.subscribe(command)
            if subscribed is not None:
                return LazyStream(subscribed)
        if self.state is not None and self.state.tools is not None:
            session = self.state.tools.stream(command)
            if session is not None:
                return BytesStream(*session)
        if self.state is not None and self.state.image is not None:
            read = self.state.image.stream(command)
            if read is not None:
                return BytesStream(read, 0)
        if self.state is not None and self.state.system is not None:
            archive = self.state.system.stream(command)
            if archive is not None:
                return BytesStream(archive, 0)
        data = self.state.fw.stream(command) if self.state is not None and self.state.fw is not None else None
        if data is None:
            return BytesStream(b"", 1, "tcpdump: no such device\n")
        return BytesStream(data, 124)  # `timeout` ends it

    async def close(self) -> None:
        return None

    def _down(self) -> None:
        """A rebooting router drops the connection, as a flash does to the app's session."""
        if self.state is not None and self.state.image is not None and self.state.image.rebooting:
            raise Unreachable("the connection was lost: the router is rebooting")
        if self.state is not None and self.state.access is not None and self.state.access.gone:
            raise Unreachable("the connection was lost: the router is resetting to defaults")

    def _simulate(self, command: str) -> CommandResult | None:
        assert self.state is not None
        self._down()
        if self.state.fw is not None:
            self.state.fw.dispatch = self._dispatch
            self.state.fw.fire(self._dispatch)  # router-side timers that came due run first
        self._down()  # a timer may have started a flash
        return self._dispatch(command)

    def _remove_old_key(self, command: str) -> CommandResult:
        """The key rotation's removal (v1.1b R5): exact lines out, only if the new line is there."""
        from openwrtgui.onboard.rotate import remove_old_key_command

        assert self.state is not None  # noqa: S101 - only the simulator has state
        tokens = shlex.split(command)
        try:
            new, old = tokens[2], tokens[tokens.index("-vxF") + 1]
        except (IndexError, ValueError):
            return CommandResult(command, "", "sim: unexpected key remove command", 1)
        if command != remove_old_key_command(new, old):
            return CommandResult(command, "", "sim: unexpected key remove command", 1)
        if new not in self.state.authorized_keys:
            return CommandResult(command, "", "", 1)  # grep -q found no new line: nothing is written
        self.state.authorized_keys[:] = [line for line in self.state.authorized_keys if line != old]
        return CommandResult(command, "", "", 0)

    def _dispatch(self, command: str) -> CommandResult | None:
        assert self.state is not None
        # A later image (v1.0a2) first: it overrides the bench image's reads it extends (menu, mounts).
        # Then the files, the image and the modem, which answer only exact commands they own; access before
        # system; then the network, the air and the Wi-Fi, which answer only commands they know whole; the
        # firewall last, since it splits compound commands and hands their parts back here.
        if self.state.later is not None and (answered := self.state.later.answer(command)) is not None:
            return answered
        if self.state.tools is not None and (answered := self.state.tools.answer(command)) is not None:
            return answered
        if self.state.files is not None and (answered := self.state.files.answer(command)) is not None:
            return answered
        if self.state.image is not None and (answered := self.state.image.answer(command)) is not None:
            return answered
        if self.state.modem is not None and (answered := self.state.modem.answer(command)) is not None:
            return answered
        # access before system: it owns `/etc/init.d/led|uhttpd restart`, which change what it serves
        if self.state.access is not None and (answered := self.state.access.answer(command)) is not None:
            return answered
        if self.state.system is not None and (answered := self.state.system.answer(command)) is not None:
            return answered
        if self.state.net is not None and (answered := self.state.net.answer(command)) is not None:
            return answered
        # the air (v0.7) before the Wi-Fi: scans, every channel's survey, frame windows
        if self.state.air is not None and (answered := self.state.air.answer(command)) is not None:
            return answered
        if self.state.wifi is not None and (answered := self.state.wifi.answer(command)) is not None:
            return answered
        if self.state.fw is not None and (answered := self.state.fw.answer(command)) is not None:
            return answered
        if command == "true":
            return CommandResult(command, "", "", 0)
        if command.startswith(INSTALL_KEY_PREFIX):
            from openwrtgui.onboard.wizard import install_key_command

            tokens = shlex.split(command)
            line = tokens[tokens.index("-qxF") + 1]
            if command != install_key_command(line):
                return CommandResult(command, "", "sim: unexpected key install command", 1)
            if line not in self.state.authorized_keys:
                self.state.authorized_keys.append(line)
            return CommandResult(command, "", "", 0)
        if command.startswith(REMOVE_KEY_PREFIX):
            return self._remove_old_key(command)
        if command.startswith("awk -F:") and command.endswith(ROOT_PASSWORD_PROBE):
            return CommandResult(command, "set\n" if self.state.root_password else "none\n", "", 0)
        return None
