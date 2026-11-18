"""App key rotation (spec 7.12, v1.1b D8): each router moves to the new key in three steps.

1. Add the new key's line (the wizard's own append, which never adds a line twice).
2. Prove a login with the new key only, over a new connection that refuses trivial auth.
3. Remove the old key's exact line: one command checks the new line is there, writes the file without the old
   lines into a temporary file and renames it over `authorized_keys` (ruling R5). The file is read back.

A router that fails keeps both lines or only the old one, so the app can always still log in.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import shlex
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.busy import RouterBusy
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited
from openwrtgui.onboard.wizard import AUTHORIZED_KEYS, Connector, install_key_command
from openwrtgui.store.keys import AppKeyRing
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import AuthFailed, Transport, TransportError
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

SCREEN = "Settings › App key rotation"
KEYS_READ = f"cat {AUTHORIZED_KEYS}"
LIVE = "App key rotation"
NEW = (
    "Make a new app key, then for each router: add the new key, log in with it, remove the old key's line. "
    "Other lines in authorized_keys are not changed."
)
CONTINUE = "Continue: {n} router(s) still on the old key."
HARNESS = "A harness run started: the rest stay on the old key"
STOPPED = "Stopped: the rest stay on the old key"
NOT_CONNECTED = "not connected yet"  # what the pool says of a router it never tried

MoveState = Literal["waiting", "adding", "proving", "removing", "moved", "failed"]


class MoveFailed(Exception):
    """A router did not move to the new key; the message is its row's detail in Settings."""


def remove_old_key_command(new_line: str, old_line: str) -> str:
    """Remove every line exactly equal to `old_line`, only if `new_line` is there; atomic on the router."""
    new, old, ak = shlex.quote(new_line), shlex.quote(old_line), AUTHORIZED_KEYS
    tmp = f"{ak}.owg"
    return f"grep -qxF {new} {ak} && grep -vxF {old} {ak} > {tmp} && chmod 600 {tmp} && mv -f {tmp} {ak}"


def _lines(text: str) -> list[str]:
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n") if text else []


async def _read_keys(t: Transport, rec: RouterRecord) -> list[str]:
    result = await t.run(KEYS_READ)
    if not result.ok:
        raise MoveFailed(f"authorized_keys on {rec.name} is not as expected: check it on System › Access")
    return _lines(result.stdout)


async def _prove(rec: RouterRecord, keys: AppKeyRing, connector: Connector) -> None:
    assert keys.next is not None  # noqa: S101 - move_router checks it
    t = await connector.connect(
        rec.host,
        rec.port,
        password=None,
        key_paths=[keys.next.private_path],
        username=rec.username,
        prove=True,
    )
    try:
        if not (await t.run("true")).ok:
            raise AuthFailed(f"{rec.host} accepted the key but did not run a command")
    finally:
        await t.close()


async def move_router(
    rec: RouterRecord,
    *,
    keys: AppKeyRing,
    pool: ConnectionPool,
    connector: Connector,
    guard: BenchGuard,
    audit: AuditLog,
    on_step: Callable[[str], None],
) -> None:
    """Move one router to the next key (D8). Raises MoveFailed with the row's detail; GuardLocked passes."""
    nxt = keys.next
    if nxt is None:
        raise ValueError("No key rotation is under way")
    old = keys.current.public_line
    did_not_answer = f"{rec.name} did not answer: it stays on the old key"
    async with pool.write_lock(rec.id):
        try:
            on_step("adding")
            t = await pool.get(rec)
            added = await run_audited(
                t,
                install_key_command(nxt.public_line),
                router_id=rec.id,
                screen=SCREEN,
                guard=guard,
                audit=audit,
            )
            if not added.ok:
                raise MoveFailed(
                    f"{rec.name} did not take the new key: {added.stderr.strip() or 'no reason given'}"
                )
            on_step("proving")
            try:
                await _prove(rec, keys, connector)
            except AuthFailed as exc:
                raise MoveFailed(f"{rec.name} did not accept the new key: the old key stays") from exc
            on_step("removing")
            before = await _read_keys(t, rec)
            expected = [line for line in before if line != old]
            removed = await run_audited(
                t,
                remove_old_key_command(nxt.public_line, old),
                router_id=rec.id,
                screen=SCREEN,
                guard=guard,
                audit=audit,
            )
            after = await _read_keys(t, rec)
        except TransportError as exc:
            raise MoveFailed(did_not_answer) from exc
        if not removed.ok or after != expected or nxt.public_line not in after:
            raise MoveFailed(f"authorized_keys on {rec.name} is not as expected: check it on System › Access")
        n = len(before) - len(expected)
        audit.record(
            router=rec.id,
            screen=SCREEN,
            command="check authorized_keys",
            exit_status=0,
            verify=f"new key logs in; {n} old line(s) removed; other lines unchanged",
            source="user",
        )
        keys.mark_moved(rec.id)
    await pool.drop(rec.id)


# ---------------------------------------------------------------- the job (Settings › App SSH key)


class RouterMove(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    name: str
    state: MoveState
    detail: str | None = None


class RotationJob(BaseModel):
    """The rotation as Settings shows it. `started_at` is None for a rotation found on disk at start-up."""

    model_config = ConfigDict(frozen=True)

    phase: Literal["running", "pending", "done"]
    old_fingerprint: str
    new_fingerprint: str
    routers: tuple[RouterMove, ...]
    started_at: datetime | None
    ended_at: datetime | None
    detail: str | None


class RotationPreview(BaseModel):
    lines: list[str]
    warnings: list[str]
    digest: str


class RotationBusy(RouterBusy):
    """A rotation already runs (409)."""


def _digest(lines: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


class KeyRotation:
    """Moves every stored router on the app's key to a new key, one router at a time (D8). Routers that fail
    stay on the old key and can be retried; the old private key is deleted only when all have moved."""

    def __init__(
        self,
        *,
        keys: AppKeyRing,
        routers: RouterStore,
        pool: ConnectionPool,
        connector: Connector,
        guard: BenchGuard,
        audit: AuditLog,
        busy: Sequence[Callable[[str], str | None]] = (),
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._keys = keys
        self._routers = routers
        self._pool = pool
        self._connector = connector
        self._guard = guard
        self._audit = audit
        self._busy = busy
        self._clock = clock
        self._job: RotationJob | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._starting = False
        self._moving: str | None = None

    # ---------------------------------------------------------------- what is moved
    def _targets(self) -> list[RouterRecord]:
        """The routers that log in with the app's own key (R7)."""
        return [r for r in self._routers.list() if r.auth == "key" and not r.key_path]

    def _waiting(self) -> list[RouterRecord]:
        moved = self._keys.moved() if self._keys.next is not None else frozenset()
        return [r for r in self._targets() if r.id not in moved]

    def _skipped(self) -> list[str]:
        out = []
        for r in self._routers.list():
            if r.auth == "key" and r.key_path:
                out.append(f"{r.name}: skipped, it logs in with your own key")
            elif r.auth != "key":
                out.append(f"{r.name}: skipped, the app key is not installed on it")
        return out

    def preview(self) -> RotationPreview:
        waiting = self._waiting()
        first = CONTINUE.format(n=len(waiting)) if self._keys.next is not None else NEW
        lines = [first, *(f"{r.name} ({r.host}): moves to the new key" for r in waiting), *self._skipped()]
        warnings = []
        for r in waiting:
            health = self._pool.health(r.id)
            if not health.online and health.error not in (None, NOT_CONNECTED):
                warnings.append(f"{r.name} does not answer now: it stays on the old key until you retry")
        return RotationPreview(lines=lines, warnings=warnings, digest=_digest(lines))

    # ---------------------------------------------------------------- the job's state
    def _running(self) -> bool:
        return self._starting or (self._task is not None and not self._task.done())

    def job(self) -> RotationJob | None:
        if self._job is None and self._keys.next is not None:
            self._job = self._found()
        return self._job

    def _found(self) -> RotationJob:
        """A rotation on disk with no job in memory (the app restarted): every target as moved or waiting."""
        nxt = self._keys.next
        assert nxt is not None  # noqa: S101 - callers check it
        moved = self._keys.moved()
        rows = tuple(
            RouterMove(router_id=r.id, name=r.name, state="moved" if r.id in moved else "waiting")
            for r in self._targets()
        )
        return RotationJob(
            phase="pending",
            old_fingerprint=self._keys.current.fingerprint,
            new_fingerprint=nxt.fingerprint,
            routers=rows,
            started_at=None,
            ended_at=None,
            detail=None,
        )

    def busy(self, router_id: str) -> str | None:
        if self._moving != router_id:
            return None
        rec = self._routers.get(router_id)
        return f"The app key is being moved on {rec.name if rec else router_id}"

    def live(self) -> list[str]:
        return [LIVE] if self._running() else []

    async def finished(self) -> RotationJob | None:
        """The job once its runner ended (tests, and stop_all)."""
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        return self.job()

    def request_stop(self) -> None:
        """Stop between routers: a router is never left between its steps."""
        if self._running():
            self._stop.set()

    async def stop_all(self, limit_s: float) -> None:
        self.request_stop()
        if self._task is not None and not self._task.done():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._task), limit_s)

    # ---------------------------------------------------------------- start, retry
    async def start(self, digest: str) -> RotationJob:
        """Begin a rotation, or continue a pending one with the routers not moved yet."""
        self._guard.require_clear()
        if self._running():
            raise RotationBusy("App key rotation already runs")
        self._starting = True
        try:
            if self.preview().digest != digest:
                raise PreviewChanged("The app's router list")
            if self._keys.next is None:
                self._keys.begin()
                self._job = None
            return self._launch([r.id for r in self._waiting()])
        finally:
            self._starting = False

    async def retry(self, router_id: str) -> RotationJob:
        self._guard.require_clear()
        if self._running():
            raise RotationBusy("App key rotation already runs")
        if self._keys.next is None:
            raise RotationBusy("No key rotation is under way")
        rec = self._routers.get(router_id)
        if rec is None or rec.id not in {r.id for r in self._waiting()}:
            raise ValueError(f"{rec.name if rec else router_id} is not waiting for the new key")
        return self._launch([rec.id])

    def _launch(self, ids: list[str]) -> RotationJob:
        base = self.job() or self._found()
        rows = {r.router_id: r for r in base.routers}
        for r in self._targets():  # a router added since, or found again
            if r.id not in rows:
                rows[r.id] = RouterMove(router_id=r.id, name=r.name, state="waiting")
        targets = {r.id for r in self._targets()}
        self._job = base.model_copy(
            update={
                "phase": "running",
                "routers": tuple(row for rid, row in rows.items() if rid in targets),
                "started_at": base.started_at or self._clock(),
                "ended_at": None,
                "detail": None,
            }
        )
        self._stop = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self._run(ids))
        return self._job

    # ---------------------------------------------------------------- the runner
    def _row(self, router_id: str, state: MoveState, detail: str | None = None) -> None:
        if self._job is None:
            return
        rows = tuple(
            r.model_copy(update={"state": state, "detail": detail}) if r.router_id == router_id else r
            for r in self._job.routers
        )
        self._job = self._job.model_copy(update={"routers": rows})

    def _why_busy(self, router_id: str) -> str | None:
        for check in self._busy:
            if (why := check(router_id)) is not None:
                return why
        return None

    async def _run(self, ids: list[str]) -> None:
        detail: str | None = None
        try:
            for router_id in ids:
                if self._stop.is_set():
                    detail = STOPPED
                    break
                if self._guard.state().live:
                    detail = HARNESS
                    break
                rec = self._routers.get(router_id)
                if rec is None:
                    continue  # removed from the app meanwhile: nothing to move
                if (why := self._why_busy(rec.id)) is not None:
                    self._row(rec.id, "failed", why)
                    continue
                if self._guard.state().live:  # a busy check may have taken a moment
                    detail = HARNESS
                    break
                self._moving = rec.id
                try:
                    await self._move(rec)
                except GuardLocked:
                    self._row(rec.id, "failed", HARNESS)
                    detail = HARNESS
                    break
                finally:
                    self._moving = None
            self._end(detail)
        except Exception as exc:  # never leave the job "running"
            log.exception("App key rotation stopped")
            self._end(f"The rotation stopped: {exc}")

    async def _move(self, rec: RouterRecord) -> None:
        def step(state: str) -> None:
            self._row(rec.id, state)  # type: ignore[arg-type]

        if not self._pool.health(rec.id).online:
            await self._pool.drop(
                rec.id
            )  # a router that failed before is tried at once, not after its backoff
        try:
            await move_router(
                rec,
                keys=self._keys,
                pool=self._pool,
                connector=self._connector,
                guard=self._guard,
                audit=self._audit,
                on_step=step,
            )
        except MoveFailed as exc:
            self._row(rec.id, "failed", str(exc))
            return
        self._row(rec.id, "moved")

    def _end(self, detail: str | None) -> None:
        assert self._job is not None  # noqa: S101 - _launch set it
        fields: dict[str, Any] = {"ended_at": self._clock(), "detail": detail}
        if self._keys.next is not None and not self._waiting():
            old = self._keys.current.fingerprint
            new = self._keys.finish()
            self._audit.record(
                router=None,
                screen=SCREEN,
                command="replace the app key on this PC",
                exit_status=0,
                verify=f"{old} -> {new.fingerprint}",
                source="user",
            )
            fields["phase"] = "done"
        else:
            fields["phase"] = "pending"
        self._job = self._job.model_copy(update=fields)
