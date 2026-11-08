"""Add-router wizard engine (spec section 5). Passwords are used once and never kept."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

import asyncssh

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import WriteAction, perform_write
from openwrtgui.probe.commands import RELEASE, ROOT_PASSWORD_STATE, SYSTEM_BOARD
from openwrtgui.probe.describe import (
    DescriptionSummary,
    SelfDescription,
    describe_router,
    propose_port_labels,
    summarize,
)
from openwrtgui.probe.identity import parse_release
from openwrtgui.store.keys import AppKey
from openwrtgui.store.routers import RouterRecord, RouterStore, make_router_id
from openwrtgui.transport.base import AuthFailed, HostKeyInfo, KeyFileError, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

log = logging.getLogger(__name__)

AUTHORIZED_KEYS = "/etc/dropbear/authorized_keys"
SCREEN = "Add router"
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "root"

# How the wizard got in: by itself (the first four) or with what the user typed (the last two).
LoginMethod = Literal["app_key", "pc_key", "default_password", "no_password", "password", "key_file"]


def install_key_command(public_line: str) -> str:
    q = shlex.quote(public_line)
    return (
        f"mkdir -p /etc/dropbear && touch {AUTHORIZED_KEYS} && chmod 600 {AUTHORIZED_KEYS} && "
        f"(grep -qxF {q} {AUTHORIZED_KEYS} || echo {q} >> {AUTHORIZED_KEYS})"
    )


class Step(StrEnum):
    ADDRESS = "address"
    HOST_KEY = "host_key"
    LOGIN = "login"
    INSTALL_KEY = "install_key"
    IDENTIFY = "identify"
    PORTS = "ports"
    DONE = "done"


def identity_of(release: str, board_json: str) -> tuple[str, str]:
    """(board_name, DISTRIB_REVISION) from `cat /etc/openwrt_release` and `ubus call system board`."""
    try:
        board = json.loads(board_json or "{}")
    except ValueError:
        board = {}
    name = str(board.get("board_name", "")) if isinstance(board, dict) else ""
    return name, parse_release(release).get("DISTRIB_REVISION", "")


async def read_identity_unchecked(host: str, port: int, timeout: float = 10.0) -> tuple[str, str]:
    """A router back from a flash without settings: root, no password, its new host key not checked. Two
    reads, then the connection is closed; nothing is pinned here. ("", "") when it does not answer."""
    try:
        conn = await asyncio.wait_for(
            asyncssh.connect(
                host,
                port,
                username=DEFAULT_USER,
                password="",
                client_keys=None,
                config=[],
                agent_path=None,
                known_hosts=None,
            ),
            timeout,
        )
    except (OSError, TimeoutError, asyncssh.Error):
        return "", ""
    try:
        async with conn:
            release = await conn.run(RELEASE, check=False, timeout=timeout)
            board = await conn.run(SYSTEM_BOARD, check=False, timeout=timeout)
    except (OSError, TimeoutError, asyncssh.Error):  # a router still booting: the usual changed-key check
        return "", ""
    return identity_of(str(release.stdout or ""), str(board.stdout or ""))


class Connector(Protocol):
    async def fetch_host_key(self, host: str, port: int) -> HostKeyInfo: ...
    async def identity_unchecked(self, host: str, port: int) -> tuple[str, str]: ...
    async def connect(
        self,
        host: str,
        port: int,
        *,
        password: str | None,
        key_paths: Sequence[Path],
        username: str = DEFAULT_USER,
        prove: bool = False,
    ) -> Transport: ...


class SshConnector:
    def __init__(self, host_keys: HostKeyStore) -> None:
        self._host_keys = host_keys

    async def fetch_host_key(self, host: str, port: int) -> HostKeyInfo:
        return await fetch_host_key(host, port)

    async def identity_unchecked(self, host: str, port: int) -> tuple[str, str]:
        return await read_identity_unchecked(host, port)

    async def connect(
        self,
        host: str,
        port: int,
        *,
        password: str | None,
        key_paths: Sequence[Path],
        username: str = DEFAULT_USER,
        prove: bool = False,
    ) -> Transport:
        return await SshTransport.connect(
            host,
            port,
            username,
            host_keys=self._host_keys,
            password=password,
            key_paths=key_paths,
            prove=prove,
        )


@dataclass(frozen=True)
class SessionView:
    sid: str
    step: Step
    host: str
    port: int
    host_key: HostKeyInfo | None
    known_before: bool
    changed_from: str | None
    root_password: str
    key_installed: bool
    summary: DescriptionSummary | None
    proposed_port_labels: dict[int, str]
    error: str | None
    username: str
    login_method: LoginMethod | None
    key_path: str | None  # a key this PC already had that the router trusts; the app will use it
    # the changed host key is the one a flash without settings made: board and revision match the image
    expected_reflash: bool = False


def _no_pc_keys() -> Sequence[Path]:
    return ()


@dataclass
class _Session:
    sid: str
    host: str
    port: int
    host_key: HostKeyInfo
    known_before: bool
    changed_from: str | None
    last_used: datetime
    step: Step = Step.HOST_KEY
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    transport: Transport | None = None
    trusted: bool = False
    root_password: str = "unknown"
    key_installed: bool = False
    key_verified: bool = False
    username: str = DEFAULT_USER
    login_method: LoginMethod | None = None
    key_path: Path | None = None
    description: SelfDescription | None = None
    error: str | None = None
    expected_reflash: bool = False


class OnboardService:
    def __init__(
        self,
        *,
        connector: Connector,
        host_keys: HostKeyStore,
        app_key: AppKey,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        pool: ConnectionPool,
        clock: Callable[[], datetime] = datetime.now,
        idle_timeout_s: int = 900,
        pc_keys: Callable[[], Sequence[Path]] = _no_pc_keys,
    ) -> None:
        self._connector = connector
        self._pc_keys = pc_keys
        self._host_keys = host_keys
        self._app_key = app_key
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._pool = pool
        self._clock = clock
        self._idle = timedelta(seconds=idle_timeout_s)
        self._sessions: dict[str, _Session] = {}

    # -- helpers -------------------------------------------------------------------------------

    async def _expire(self) -> None:
        now = self._clock()
        for sid, s in list(self._sessions.items()):
            if now - s.last_used > self._idle:
                await self.cancel(sid)

    async def _get(self, sid: str) -> _Session:
        await self._expire()
        session = self._sessions[sid]
        session.last_used = self._clock()
        return session

    @staticmethod
    def _view(s: _Session) -> SessionView:
        return SessionView(
            sid=s.sid,
            step=s.step,
            host=s.host,
            port=s.port,
            host_key=s.host_key,
            known_before=s.known_before,
            changed_from=s.changed_from,
            root_password=s.root_password,
            key_installed=s.key_installed,
            summary=summarize(s.description) if s.description else None,
            proposed_port_labels=propose_port_labels(s.description.board) if s.description else {},
            error=s.error,
            username=s.username,
            login_method=s.login_method,
            key_path=str(s.key_path) if s.key_path else None,
            expected_reflash=s.expected_reflash,
        )

    @staticmethod
    def _transport(s: _Session) -> Transport:
        if s.transport is None:
            raise ValueError("Log in to the router first")
        return s.transport

    @staticmethod
    def _require_trusted(s: _Session) -> None:
        if not s.trusted:
            raise ValueError("Accept the router's host key first")

    @staticmethod
    async def _logged_in(s: _Session, transport: Transport, method: LoginMethod) -> None:
        if s.transport is not None:
            await s.transport.close()
        s.transport = transport
        # A new login replaces whatever an earlier one proved.
        s.key_verified = False
        s.key_installed = False
        s.key_path = None
        state = (await transport.run(ROOT_PASSWORD_STATE)).stdout.strip()
        s.root_password = state if state in ("none", "set") else "unknown"
        s.login_method = method
        s.step = Step.INSTALL_KEY

    # -- steps ---------------------------------------------------------------------------------

    def view(self, sid: str) -> SessionView:
        return self._view(self._sessions[sid])

    async def start(self, host: str, port: int = 22) -> SessionView:
        await self._expire()
        info = await self._connector.fetch_host_key(host, port)
        pinned = self._host_keys.get(host, port)
        session = _Session(
            sid=uuid.uuid4().hex[:12],
            host=host,
            port=port,
            host_key=info,
            known_before=pinned == info.fingerprint,
            changed_from=pinned if pinned and pinned != info.fingerprint else None,
            last_used=self._clock(),
        )
        if session.changed_from is not None:
            session.expected_reflash = await self._expected_reflash(host, port)
        self._sessions[session.sid] = session
        return self._view(session)

    async def _expected_reflash(self, host: str, port: int) -> bool:
        """A router at this address was flashed without settings: read its board and revision before anything
        is pinned (that one connection checks no host key and is closed at once); equal to the image → the new
        host key is the one the flash made."""
        pending = next(
            (r.reflashed for r in self._routers.list() if r.reflashed and (r.host, r.port) == (host, port)),
            None,
        )
        if pending is None:
            return False
        board, revision = await self._connector.identity_unchecked(host, port)
        return (board, revision) == (pending.board, pending.revision)

    async def trust(self, sid: str, fingerprint: str) -> SessionView:
        s = await self._get(sid)
        if fingerprint != s.host_key.fingerprint:
            raise ValueError("That fingerprint is not the one this router sent")
        self._host_keys.pin(s.host, s.port, s.host_key)
        s.trusted = True
        s.changed_from = None
        s.step = Step.LOGIN
        return self._view(s)

    async def auto_login(self, sid: str) -> SessionView:
        """Log in with nothing typed: the app key, this PC's own keys, root/root, then nothing.

        The key and password tries must prove themselves (a router with an empty root password
        lets anything in, which proves nothing); only the last try may get in without
        credentials, and that is reported as "no_password". A key that works means nothing
        gets installed. If nothing works the session stays at LOGIN for the user to type.
        A router that stops answering is raised, not hidden.
        """
        s = await self._get(sid)
        self._require_trusted(s)
        app_key = self._app_key.private_path
        tries: list[tuple[LoginMethod, str | None, Path | None]] = [("app_key", None, app_key)]
        tries += [("pc_key", None, p) for p in self._pc_keys() if p != app_key]
        tries.append(("default_password", DEFAULT_PASSWORD, None))
        tries.append(("no_password", None, None))
        for method, password, key in tries:
            try:
                transport = await self._connector.connect(
                    s.host,
                    s.port,
                    username=s.username,
                    password=password,
                    key_paths=[key] if key else [],
                    prove=method != "no_password",
                )
            except AuthFailed:
                continue
            except KeyFileError as exc:  # went away or will not load since it was found
                log.info("auto-login skipped: %s", exc)
                continue
            await self._logged_in(s, transport, method)
            if key is not None and s.root_password != "none":
                s.key_verified = True
                s.key_installed = method == "app_key"
                s.key_path = key if method == "pc_key" else None
                s.step = Step.IDENTIFY
            elif s.root_password == "none":
                s.login_method = "no_password"
            return self._view(s)
        return self._view(s)

    async def login(
        self,
        sid: str,
        *,
        password: str | None = None,
        key_path: Path | None = None,
        username: str = DEFAULT_USER,
    ) -> SessionView:
        s = await self._get(sid)
        self._require_trusted(s)
        user = username.strip() or DEFAULT_USER
        key_paths = [key_path] if key_path else []
        transport = await self._connector.connect(
            s.host,
            s.port,
            username=user,
            password=password if key_path is None else None,
            key_paths=key_paths,
        )
        s.username = user
        await self._logged_in(s, transport, "key_file" if key_path else "password")
        return self._view(s)

    def install_key_preview(self, sid: str) -> list[str]:
        self._sessions[sid].last_used = self._clock()
        return [install_key_command(self._app_key.public_line)]

    async def install_key(self, sid: str) -> SessionView:
        s = await self._get(sid)
        action = WriteAction(
            router_id=f"onboard:{s.sid}",
            screen=SCREEN,
            commands=(install_key_command(self._app_key.public_line),),
        )
        results = await perform_write(
            action,
            transport=self._transport(s),
            lock=s.lock,
            guard=self._guard,
            audit=self._audit,
            source="wizard",
        )
        if not results[-1].ok:
            s.error = results[-1].stderr.strip() or "Installing the key failed"
            raise TransportError(s.error)
        s.key_installed = True
        s.error = None
        return self._view(s)

    async def set_password(self, sid: str, new_password: str) -> SessionView:
        s = await self._get(sid)
        if s.root_password != "none":
            raise ValueError("The router already has a root password")
        if not new_password:
            raise ValueError("Type a password")
        action = WriteAction(
            router_id=f"onboard:{s.sid}",
            screen=SCREEN,
            commands=("passwd root",),
            secrets=(new_password,),
            stdin=f"{new_password}\n{new_password}\n",
        )
        results = await perform_write(
            action,
            transport=self._transport(s),
            lock=s.lock,
            guard=self._guard,
            audit=self._audit,
            source="wizard",
        )
        if not results[-1].ok:
            raise TransportError(results[-1].stderr.strip() or "Setting the password failed")
        s.root_password = "set"
        return self._view(s)

    async def verify_key(self, sid: str) -> SessionView:
        s = await self._get(sid)
        t = await self._connector.connect(
            s.host, s.port, username=s.username, password=None, key_paths=[self._app_key.private_path]
        )
        try:
            ok = (await t.run("true")).ok
        finally:
            await t.close()
        if not ok:
            raise TransportError("The router accepted the key but did not run a command")
        s.key_installed = True
        s.key_verified = True
        s.key_path = None
        s.step = Step.IDENTIFY
        return self._view(s)

    async def identify(self, sid: str) -> SessionView:
        s = await self._get(sid)
        s.description = await describe_router(self._transport(s))
        s.step = Step.PORTS
        return self._view(s)

    async def finish(self, sid: str, name: str, port_labels: dict[int, str]) -> RouterRecord:
        s = await self._get(sid)
        existing = [r.id for r in self._routers.list() if r.host != s.host or r.port != s.port]
        label = name.strip() or (s.description.identity.hostname if s.description else s.host)
        previous = next((r for r in self._routers.list() if r.host == s.host and r.port == s.port), None)
        record = RouterRecord(
            id=previous.id if previous else make_router_id(label, existing),
            name=label,
            host=s.host,
            port=s.port,
            username=s.username,
            auth="key" if s.key_verified else "none",
            key_path=str(s.key_path) if s.key_path else None,
            port_labels=dict(port_labels),
            added_at=self._clock(),
        )
        self._routers.upsert(record)
        await self._pool.drop(record.id)
        s.step = Step.DONE
        await self.cancel(sid)
        return record

    async def cancel(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is not None and s.transport is not None:
            try:
                await s.transport.close()
            except (TransportError, OSError):
                log.debug("closing the wizard connection failed", exc_info=True)
