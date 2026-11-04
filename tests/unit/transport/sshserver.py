"""An in-process asyncssh server standing in for a router's dropbear."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import asyncssh

TEST_PASSWORD = "test-pw"


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == "root" and password == TEST_PASSWORD


class _NoLoginServer(_Server):
    """Like dropbear with an empty root password: anyone gets in without credentials."""

    def begin_auth(self, username: str) -> bool:
        return False


async def _handle(process: asyncssh.SSHServerProcess[str]) -> None:
    cmd = process.command
    if cmd == "echo hi":
        process.stdout.write("hi\n")
        process.exit(0)
    elif cmd == "cat":
        data = await process.stdin.read()
        process.stdout.write(data)
        process.exit(0)
    elif cmd is None:
        process.stdout.write("shell> ")
        line = await process.stdin.readline()
        process.stdout.write(f"you typed {line.strip()}\n")
        process.exit(0)
    else:
        process.stderr.write(f"unknown: {cmd}\n")
        process.exit(127)


@dataclass
class SshServer:
    port: int
    fingerprint: str
    server: asyncssh.SSHAcceptor


async def start_server(authorized: Sequence[str] = (), *, no_login: bool = False) -> SshServer:
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    auth_keys = asyncssh.import_authorized_keys("\n".join(authorized) + "\n") if authorized else None
    acceptor = await asyncssh.create_server(
        _NoLoginServer if no_login else _Server,
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        process_factory=_handle,
        authorized_client_keys=auth_keys,
    )
    port = acceptor.sockets[0].getsockname()[1]
    return SshServer(port=port, fingerprint=host_key.get_fingerprint("sha256"), server=acceptor)
