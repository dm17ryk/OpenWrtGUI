"""Add-router wizard engine (spec section 5). Passwords are used once and never kept."""

from __future__ import annotations

import asyncio
import logging
import shlex
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import WriteAction, perform_write
from openwrtgui.probe.commands import ROOT_PASSWORD_STATE
from openwrtgui.probe.describe import (
    DescriptionSummary,
    SelfDescription,
    describe_router,
    propose_port_labels,
    summarize,
)
from openwrtgui.store.keys import AppKey
from openwrtgui.store.routers import RouterRecord, RouterStore, make_router_id
from openwrtgui.transport.base import HostKeyInfo, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, SshTransport, fetch_host_key

log = logging.getLogger(__name__)

AUTHORIZED_KEYS = "/etc/dropbear/authorized_keys"
SCREEN = "Add router"


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


class Connector(Protocol):
    async def fetch_host_key(self, host: str, port: int) -> HostKeyInfo: ...
    async def connect(
        self, host: str, port: int, *, password: str | None, key_paths: Sequence[Path]
    ) -> Transport: ...


class SshConnector:
    def __init__(self, host_keys: HostKeyStore) -> None:
        self._host_keys = host_keys

    async def fetch_host_key(self, host: str, port: int) -> HostKeyInfo:
        return await fetch_host_key(host, port)

    async def connect(
        self, host: str, port: int, *, password: str | None, key_paths: Sequence[Path]
    ) -> Transport:
        return await SshTransport.connect(
            host, port, "root", host_keys=self._host_keys, password=password, key_paths=key_paths
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
    description: SelfDescription | None = None
    error: str | None = None


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
    ) -> None:
        self._connector = connector
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
        )

    @staticmethod
    def _transport(s: _Session) -> Transport:
        if s.transport is None:
            raise ValueError("Log in to the router first")
        return s.transport

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
        self._sessions[session.sid] = session
        return self._view(session)

    async def trust(self, sid: str, fingerprint: str) -> SessionView:
        s = await self._get(sid)
        if fingerprint != s.host_key.fingerprint:
            raise ValueError("That fingerprint is not the one this router sent")
        self._host_keys.pin(s.host, s.port, s.host_key)
        s.trusted = True
        s.changed_from = None
        s.step = Step.LOGIN
        return self._view(s)

    async def login(
        self, sid: str, *, password: str | None = None, key_path: Path | None = None
    ) -> SessionView:
        s = await self._get(sid)
        if not s.trusted:
            raise ValueError("Accept the router's host key first")
        key_paths = [key_path] if key_path else []
        transport = await self._connector.connect(
            s.host, s.port, password=password if key_path is None else None, key_paths=key_paths
        )
        if s.transport is not None:
            await s.transport.close()
        s.transport = transport
        state = (await transport.run(ROOT_PASSWORD_STATE)).stdout.strip()
        s.root_password = state if state in ("none", "set") else "unknown"
        s.step = Step.INSTALL_KEY
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
            s.host, s.port, password=None, key_paths=[self._app_key.private_path]
        )
        try:
            ok = (await t.run("true")).ok
        finally:
            await t.close()
        if not ok:
            raise TransportError("The router accepted the key but did not run a command")
        s.key_installed = True
        s.key_verified = True
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
            auth="key" if s.key_verified else "none",
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
