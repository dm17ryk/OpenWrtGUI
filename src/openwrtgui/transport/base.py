"""The transport contract every router connection follows, and ubus helpers."""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

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


class Transport(Protocol):
    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult: ...
    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult: ...
    async def open_shell(self, cols: int, rows: int) -> ShellChannel: ...
    async def close(self) -> None: ...


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
