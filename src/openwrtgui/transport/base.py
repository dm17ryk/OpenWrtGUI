"""The transport contract every router connection follows, and ubus helpers."""

from __future__ import annotations

import json
import shlex
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

UBUS_METHOD_NOT_FOUND = 3
UBUS_NOT_FOUND = 4


@dataclass(frozen=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_status: int

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


@dataclass(frozen=True)
class HostKeyInfo:
    type: str
    fingerprint: str
    public: str


class TransportError(Exception):
    """Talking to the router failed."""


class Unreachable(TransportError):
    def __init__(self, message: str, retry_at: datetime | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


class AuthFailed(TransportError):
    """The router refused the login."""


class KeyFileError(TransportError):
    """A key file on this PC is missing, unreadable or needs a passphrase. The router was not asked."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"The key file {path} cannot be used: {reason}")
        self.path = path


class HostKeyUnknown(TransportError):
    def __init__(self, host: str, actual: HostKeyInfo) -> None:
        super().__init__(f"{host} has no pinned host key yet ({actual.fingerprint})")
        self.host = host
        self.actual = actual


class HostKeyChanged(TransportError):
    def __init__(self, host: str, expected: str, actual: HostKeyInfo) -> None:
        super().__init__(
            f"The host key of {host} changed: pinned {expected}, now {actual.fingerprint}. "
            "A reflash regenerates the host key; re-pin it through Add router if this is expected."
        )
        self.host = host
        self.expected = expected
        self.actual = actual


class ShellChannel(Protocol):
    async def write(self, data: str) -> None: ...
    async def read(self) -> str: ...
    async def resize(self, cols: int, rows: int) -> None: ...
    async def close(self) -> None: ...


class ByteStream(Protocol):
    """A command's stdout as bytes, as it comes (a capture); its exit status and stderr once closed."""

    exit_status: int | None
    stderr: str

    async def read(self, n: int = 65536) -> bytes: ...  # b"" at the end
    async def close(self) -> None: ...


class Streamer(Protocol):
    async def stream(self, command: str) -> ByteStream: ...


UPLOAD_CHUNK = 65536


@runtime_checkable
class Uploader(Protocol):
    """Bytes to a command's stdin (`cat > <path>`), in UPLOAD_CHUNK pieces; progress(sent) after each."""

    async def upload(
        self,
        command: str,
        data: bytes,
        progress: Callable[[int], None] | None = None,
        *,
        timeout: float = 600.0,
    ) -> CommandResult: ...


class Transport(Protocol):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult: ...
    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult: ...
    async def open_shell(self, cols: int, rows: int) -> ShellChannel: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class LocalForward:
    """A loopback port on this PC that reaches a host:port as seen from the router."""

    port: int
    close: Callable[[], Awaitable[None]]


@runtime_checkable
class Forwarder(Protocol):
    """Transports that can forward a local port (SSH can; the simulator cannot)."""

    async def forward_local(self, remote_host: str, remote_port: int) -> LocalForward: ...


def ubus_command(obj: str, method: str, args: Mapping[str, object] | None = None) -> str:
    cmd = f"ubus call {obj} {method}"
    if args:
        cmd += " " + shlex.quote(json.dumps(args, separators=(",", ":"), sort_keys=True))
    return cmd


async def ubus_call(
    t: Transport, obj: str, method: str, args: Mapping[str, object] | None = None
) -> dict[str, Any] | None:
    """Call a ubus method; None when the object or method does not exist on this router."""
    result = await t.run(ubus_command(obj, method, args))
    if result.exit_status in (UBUS_METHOD_NOT_FOUND, UBUS_NOT_FOUND):
        return None
    if not result.ok:
        raise TransportError(result.stderr.strip() or f"{result.command} exited {result.exit_status}")
    if not result.stdout.strip():
        return {}
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise TransportError(f"{result.command} returned {type(data).__name__}, not an object")
    return data
