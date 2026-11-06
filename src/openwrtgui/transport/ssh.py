"""SSH transport (asyncssh) with pinned host keys. Never auto-accepts a host key."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

import asyncssh

from openwrtgui.store import write_atomic
from openwrtgui.transport.base import (
    AuthFailed,
    CommandResult,
    HostKeyChanged,
    HostKeyInfo,
    HostKeyUnknown,
    KeyFileError,
    LocalForward,
    ShellChannel,
    Unreachable,
)

log = logging.getLogger(__name__)


def _host_pattern(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def _info(key: asyncssh.SSHKey) -> HostKeyInfo:
    return HostKeyInfo(
        type=key.get_algorithm(),
        fingerprint=key.get_fingerprint("sha256"),
        public=key.export_public_key("openssh").decode("ascii").strip(),
    )


class HostKeyStore:
    """Pinned host keys in OpenSSH known_hosts format, usable by asyncssh directly."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def get(self, host: str, port: int) -> str | None:
        pattern = _host_pattern(host, port)
        for line in self._lines():
            name, _, key_text = line.partition(" ")
            if name == pattern:
                return str(asyncssh.import_public_key(key_text).get_fingerprint("sha256"))
        return None

    def key_type(self, host: str, port: int) -> str | None:
        """The type of the key pinned for `host` (ssh-ed25519, ecdsa-sha2-nistp256, ...)."""
        pattern = _host_pattern(host, port)
        for line in self._lines():
            name, _, key_text = line.partition(" ")
            if name == pattern:
                return key_text.split()[0]
        return None

    def pin(self, host: str, port: int, info: HostKeyInfo) -> None:
        pattern = _host_pattern(host, port)
        kept = [ln for ln in self._lines() if ln.partition(" ")[0] != pattern]
        kept.append(f"{pattern} {info.public}")
        write_atomic(self.path, "\n".join(kept) + "\n")

    def carry(self, old_host: str, new_host: str, port: int, actual: HostKeyInfo) -> bool:
        """Pin `actual` for `new_host` only when it is the key pinned for `old_host`: the same router at a
        new address. Any other key is not trusted here."""
        pinned = self.get(old_host, port)
        if pinned is None or pinned != actual.fingerprint:
            return False
        self.pin(new_host, port, actual)
        return True

    def forget(self, host: str, port: int) -> None:
        pattern = _host_pattern(host, port)
        kept = [ln for ln in self._lines() if ln.partition(" ")[0] != pattern]
        write_atomic(self.path, "\n".join(kept) + ("\n" if kept else ""))


async def fetch_host_key(
    host: str, port: int = 22, timeout: float = 10.0, algs: Sequence[str] = ()
) -> HostKeyInfo:
    """The router's host key; of the types in `algs` when given (a router has several, one per type)."""
    try:
        key = await asyncio.wait_for(
            asyncssh.get_server_host_key(host, port, server_host_key_algs=list(algs) or ()), timeout
        )
    except (OSError, TimeoutError, asyncssh.Error) as exc:
        raise Unreachable(f"{host}:{port} did not answer: {exc}") from exc
    if key is None:
        raise Unreachable(f"{host}:{port} sent no host key")
    return _info(key)


def _load_keys(key_paths: Sequence[Path]) -> list[asyncssh.SSHKeyPair]:
    """Load before connecting, so a bad key file is reported as such and not as "unreachable"."""
    keys: list[asyncssh.SSHKeyPair] = []
    for path in key_paths:
        try:
            keys.extend(asyncssh.load_keypairs([str(path)]))
        except (OSError, ValueError) as exc:  # KeyImportError is a ValueError: passphrase or not a key
            raise KeyFileError(str(path), str(exc)) from exc
    return keys


class _Shell:
    def __init__(self, process: asyncssh.SSHClientProcess[str]) -> None:
        self._process = process

    async def write(self, data: str) -> None:
        self._process.stdin.write(data)

    async def read(self) -> str:
        return str(await self._process.stdout.read(4096))

    async def resize(self, cols: int, rows: int) -> None:
        self._process.change_terminal_size(cols, rows)

    async def close(self) -> None:
        self._process.close()
        await self._process.wait_closed()


class SshTransport:
    def __init__(self, conn: asyncssh.SSHClientConnection, host: str) -> None:
        self._conn = conn
        self.host = host

    @classmethod
    async def connect(
        cls,
        host: str,
        port: int,
        username: str,
        *,
        host_keys: HostKeyStore,
        password: str | None = None,
        key_paths: Sequence[Path] = (),
        timeout: float = 10.0,
        prove: bool = False,
    ) -> SshTransport:
        """Log in with exactly the given password and key files, nothing from ~/.ssh.

        prove=True refuses a router that lets us in without checking anything (an empty root
        password), so a successful login proves that the key or password really works.
        """
        pinned = host_keys.get(host, port)
        if pinned is None:
            raise HostKeyUnknown(host, await fetch_host_key(host, port, timeout))
        client_keys = _load_keys(key_paths)
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(
                    host,
                    port,
                    username=username,
                    password=password,
                    # [] would make asyncssh load ~/.ssh/id_*, and () reads ~/.ssh/config.
                    client_keys=client_keys or None,
                    config=[],
                    agent_path=None,
                    known_hosts=str(host_keys.path),
                    disable_trivial_auth=prove,
                ),
                timeout,
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise HostKeyChanged(host, pinned, await fetch_host_key(host, port, timeout)) from exc
        except asyncssh.PermissionDenied as exc:
            raise AuthFailed(f"{host} refused the login") from exc
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            raise Unreachable(f"{host}:{port}: {exc}") from exc
        log.debug("connected to %s:%s as %s", host, port, username)
        return cls(conn, host)

    async def run(self, command: str, *, timeout: float = 15.0) -> CommandResult:
        return await self._run(command, None, timeout)

    async def run_stdin(self, command: str, stdin: str, *, timeout: float = 15.0) -> CommandResult:
        return await self._run(command, stdin, timeout)

    async def _run(self, command: str, stdin: str | None, timeout: float) -> CommandResult:
        try:
            done = await self._conn.run(command, input=stdin, check=False, timeout=timeout)
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            # asyncssh's TimeoutError has no text of its own
            why = str(exc).strip() or (
                f"no answer within {timeout:g} s" if isinstance(exc, TimeoutError) else ""
            )
            raise Unreachable(f"{self.host}: {why or type(exc).__name__}") from exc
        status = done.exit_status if done.exit_status is not None else -1
        return CommandResult(command, str(done.stdout or ""), str(done.stderr or ""), status)

    async def open_shell(self, cols: int, rows: int) -> ShellChannel:
        process = await self._conn.create_process(term_type="xterm-256color", term_size=(cols, rows))
        return _Shell(process)

    async def forward_local(self, remote_host: str, remote_port: int) -> LocalForward:
        try:
            listener = await self._conn.forward_local_port("127.0.0.1", 0, remote_host, remote_port)
        except (OSError, asyncssh.Error) as exc:
            raise Unreachable(f"{self.host}: cannot forward to {remote_host}:{remote_port}: {exc}") from exc

        async def close() -> None:
            listener.close()
            await listener.wait_closed()

        return LocalForward(port=listener.get_port(), close=close)

    async def close(self) -> None:
        self._conn.close()
        await self._conn.wait_closed()
