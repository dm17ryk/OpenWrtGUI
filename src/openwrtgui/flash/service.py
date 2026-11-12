"""Flash a router from an imported image (v0.5 plan, "Flash rules"): upload, check it on the router, start
sysupgrade through the router-side timer, wait for the router to come back and prove the new revision.

Every step before the timer is armed can fail cleanly: the partial file is removed and nothing is flashed.
Once armed the flash cannot be stopped; the job then only reports what it sees.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.busy import RouterBusy
from openwrtgui.discovery.service import DiscoveryService
from openwrtgui.flash.plan import KEEP_LINE, FlashPlan, FlashRequest, flash_plan, fw_path, read_facts
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited, run_audited_upload
from openwrtgui.images.profile import ProfileKey
from openwrtgui.images.store import ProfileStore
from openwrtgui.net.service import NetworkService
from openwrtgui.probe.commands import RELEASE, SYSTEM_BOARD
from openwrtgui.probe.identity import parse_release
from openwrtgui.store.routers import ReflashPending, RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, HostKeyChanged, Transport, TransportError
from openwrtgui.transport.comeback import wait_for_reboot
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)
SCREEN = "Discovery"
Phase = Literal["upload", "check", "arm", "wait", "prove", "done", "failed"]


class FlashJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    router_id: str
    phase: Phase
    sent: int
    total: int
    started_at: datetime
    error: str | None = None
    detail: str | None = None


class ImageCheck(BaseModel):
    """What an upload-and-validate without a flash found."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    detail: str


class FlashBusy(RouterBusy):
    """Another job holds the router: no flash until it ends (v0.7 D8, 409)."""


class _Failed(Exception):
    """A step before sysupgrade failed; the message is the job's error."""


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _duration(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        return f"{int(seconds // 60)} minutes"
    return f"{seconds:g} s"


class FlashService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        profiles: ProfileStore,
        discovery: DiscoveryService,
        net: NetworkService,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        come_back_s: float = 600.0,
        every_s: float = 5.0,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._profiles = profiles
        self._discovery = discovery
        self._net = net
        self._clock = clock
        self._sleep = sleep
        self._monotonic = monotonic
        self.come_back_s = come_back_s
        self.every_s = every_s
        self._jobs: dict[str, FlashJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._starting: set[str] = set()  # past its checks, still reading the router before its job exists
        self.extra_busy: Callable[[str], str | None] | None = None  # a step-through (v0.7 D8)

    def job(self, router_id: str) -> FlashJob | None:
        return self._jobs.get(router_id)

    def running(self, router_id: str) -> bool:
        """A flash runs, or one is starting: other jobs on the router wait for it either way."""
        job = self._jobs.get(router_id)
        return router_id in self._starting or (job is not None and job.phase not in ("done", "failed"))

    def _update(self, router_id: str, **fields: object) -> None:
        self._jobs[router_id] = self._jobs[router_id].model_copy(update=fields)

    async def _prepare(self, router_id: str, req: FlashRequest) -> tuple[RouterRecord, bytes, FlashPlan, str]:
        rec, t, desc = await self._discovery.described(router_id)
        key = ProfileKey(board=req.board, revision=req.revision, sha256=req.sha256)
        profile = self._profiles.get(key)
        if profile is None:
            raise ValueError(f"No imported image {key.label}")
        image = self._profiles.image_bytes(key)
        net = await self._net.state(rec.id)
        facts = await read_facts(t, desc.identity.board_name, desc.identity.revision, net)
        return rec, image, flash_plan(rec.name, profile, image, req, facts), desc.identity.board_name

    async def plan(self, router_id: str, req: FlashRequest) -> FlashPlan:
        return (await self._prepare(router_id, req))[2]

    async def start(self, router_id: str, req: FlashRequest, digest: str) -> FlashJob:
        if self.extra_busy is not None and (why := self.extra_busy(router_id)) is not None:
            raise FlashBusy(why)
        if self.running(router_id):
            raise FlashBusy("A flash runs on this router already")
        self._guard.require_clear()
        self._starting.add(router_id)  # no await since the checks: a step-through cannot get in between
        try:
            return await self._start(router_id, req, digest)
        finally:
            self._starting.discard(router_id)

    async def _start(self, router_id: str, req: FlashRequest, digest: str) -> FlashJob:
        rec, image, plan, board = await self._prepare(router_id, req)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        job = FlashJob(router_id=rec.id, phase="upload", sent=0, total=len(image), started_at=self._clock())
        self._jobs[rec.id] = job
        task = asyncio.create_task(self._run(rec, req, plan, image, board))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(
        self, rec: RouterRecord, req: FlashRequest, plan: FlashPlan, image: bytes, board: str
    ) -> None:
        try:
            armed_at = await self._send(rec, req, plan, image)
            if not req.keep_settings:
                self._reflashed(rec, req, board)
                await self._pool.drop(rec.id)
                return
            await self._come_back(rec, req, board, armed_at)
        except _Failed as exc:
            self._update(rec.id, phase="failed", error=str(exc))
        except Exception as exc:  # the job must end in a phase the UI shows, whatever broke
            log.exception("flash of %s failed", rec.id)
            self._update(rec.id, phase="failed", error=str(exc) or type(exc).__name__)

    def _reflashed(self, rec: RouterRecord, req: FlashRequest, board: str) -> None:
        """Without settings the router comes back as 192.168.1.1, no password, no key: the entry waits."""
        pending = ReflashPending(board=board, revision=req.revision, at=self._clock())
        self._routers.upsert(rec.model_copy(update={"reflashed": pending}))
        self._discovery.forget(rec.id)
        self._update(
            rec.id,
            phase="done",
            detail=(
                f"Reflashed without settings: {rec.name} comes back as 192.168.1.1 with no password. "
                "Connect it alone to this PC, then add it again."
            ),
        )

    async def _step(
        self, t: Transport, rec: RouterRecord, command: str, timeout: float = 60.0
    ) -> CommandResult:
        result = await run_audited(
            t, command, router_id=rec.id, screen=SCREEN, guard=self._guard, audit=self._audit, timeout=timeout
        )
        if not result.ok:
            raise _Failed(f"{command}: {_reason(result)}")
        return result

    async def _check_image(self, t: Transport, rec: RouterRecord, req: FlashRequest, plan: FlashPlan) -> None:
        path = fw_path(req.sha256)
        got = (await self._step(t, rec, f"sha256sum {path}")).stdout.split()[:1]
        if got != [req.sha256]:
            raise _Failed(f"{rec.name} received a different file (sha256 {(got or ['nothing'])[0][:12]})")
        answer = await self._step(t, rec, plan.lines[3])
        try:
            validated = json.loads(answer.stdout)
        except ValueError as exc:
            raise _Failed(f"{rec.name} gave no answer on the image") from exc
        if not validated.get("valid"):
            failed = [name for name, ok in (validated.get("tests") or {}).items() if ok is False]
            raise _Failed(f"{rec.name} refused the image: {', '.join(failed) or 'invalid image'}")
        tested = await run_audited(
            t,
            plan.lines[4],
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            timeout=60.0,
        )
        if not tested.ok:
            raise _Failed(f"{rec.name} refused the image: {_reason(tested)}")

    async def _upload(
        self, t: Transport, rec: RouterRecord, plan: FlashPlan, image: bytes, progress: Callable[[int], None]
    ) -> None:
        await self._step(t, rec, "mkdir -p /tmp/owg")
        uploaded = await run_audited_upload(
            t,
            plan.upload_command,
            image,
            name=plan.lines[1].split("# stdin: ", 1)[1].split(" (", 1)[0],
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            progress=progress,
        )
        if not uploaded.ok:
            raise _Failed(f"The upload to {rec.name} failed: {_reason(uploaded)}")

    async def check_only(self, router_id: str, req: FlashRequest, digest: str) -> ImageCheck:
        """Upload and validate without flashing (the AP2 window before a flash): the plan's steps up to
        `sysupgrade -T`, then the file and an empty /tmp/owg taken away again. No job, checklist or timer."""
        self._guard.require_clear()
        rec, image, plan, _board = await self._prepare(router_id, req)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        t = await self._pool.get(rec)
        async with self._pool.write_lock(rec.id):
            try:
                await self._upload(t, rec, plan, image, lambda _sent: None)
                await self._check_image(t, rec, req, plan)
                check = ImageCheck(
                    ok=True, detail=f"{rec.name} accepted the image (validate_firmware_image, sysupgrade -T)"
                )
            except (_Failed, TransportError) as exc:
                check = ImageCheck(ok=False, detail=str(exc))
            finally:
                await self._remove(t, rec, fw_path(req.sha256))
                await run_audited(
                    t,
                    "rmdir /tmp/owg 2>/dev/null || true",
                    router_id=rec.id,
                    screen=SCREEN,
                    guard=self._guard,
                    audit=self._audit,
                    require_guard=False,
                )
        return check

    async def _send(self, rec: RouterRecord, req: FlashRequest, plan: FlashPlan, image: bytes) -> float:
        path = fw_path(req.sha256)
        t = await self._pool.get(rec)
        async with self._pool.write_lock(rec.id):
            try:
                await self._upload(t, rec, plan, image, lambda sent: self._update(rec.id, sent=sent))
                self._update(rec.id, phase="check")
                await self._check_image(t, rec, req, plan)
                try:
                    await self._discovery.save_checklist(rec.id)
                except (ValueError, TransportError) as exc:
                    log.info("no reflash checklist for %s: %s", rec.id, exc)
                if KEEP_LINE in plan.lines:
                    await self._step(t, rec, KEEP_LINE)
                self._update(rec.id, phase="arm")
                self._guard.require_clear()
                await self._step(t, rec, plan.lines[-1])
                return self._monotonic()
            except Exception as exc:  # whatever stopped it before sysupgrade, the image does not stay behind
                remover: Transport | None = t
                if isinstance(exc, TransportError):  # that connection is gone: remove the file on a new one
                    await self._pool.drop(rec.id)
                    try:
                        remover = await self._pool.get(rec)
                    except TransportError:
                        remover = None
                if remover is not None:
                    await self._remove(remover, rec, path)
                if isinstance(exc, GuardLocked):
                    raise _Failed(f"Stopped before sysupgrade: Bench Guard sees {exc}") from exc
                if isinstance(exc, TransportError):
                    raise _Failed(f"Stopped before sysupgrade: {exc}") from exc
                raise

    async def _remove(self, t: Transport, rec: RouterRecord, path: str) -> None:
        """Take the uploaded file away again (allowed during a run: it only undoes what the flash sent)."""
        try:
            await run_audited(
                t,
                f"rm -f {path}",
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                require_guard=False,
            )
        except TransportError:
            log.info("could not remove %s from %s", path, rec.id)

    async def _come_back(self, rec: RouterRecord, req: FlashRequest, board: str, armed_at: float) -> None:
        self._update(rec.id, phase="wait")

        async def prove(t: Transport, uptime: float) -> tuple[str, str]:
            revision = parse_release((await t.run(RELEASE)).stdout).get("DISTRIB_REVISION", "")
            answered = json.loads((await t.run(SYSTEM_BOARD)).stdout or "{}")
            return revision, str(answered.get("board_name", ""))

        try:  # the timer starts sysupgrade 2 s after it was armed: until then the old system answers
            back = await wait_for_reboot(
                self._pool,
                rec,
                armed_at=armed_at,
                clock=self._monotonic,
                sleep=self._sleep,
                every_s=self.every_s,
                limit_s=self.come_back_s,
                prove=prove,
            )
        except HostKeyChanged as exc:
            raise _Failed(str(exc)) from exc
        if back is None or back.proof is None:
            raise _Failed(
                f"{rec.name} did not come back within {_duration(self.come_back_s)}. It may still be "
                "writing flash: do not power it off; check its LEDs, then try Reconnect."
            )
        self._update(rec.id, phase="prove")
        revision, found = back.proof
        if found != board:
            raise _Failed(f"{rec.name} answers as {found or 'an unknown board'}, not {board}")
        if revision != req.revision:
            raise _Failed(f"{rec.name} came back on {revision or 'an unknown revision'}, not {req.revision}")
        minutes, seconds = divmod(int(back.elapsed_s), 60)
        self._discovery.forget(rec.id)
        self._update(
            rec.id,
            phase="done",
            detail=f"Flashed {rec.name} with {req.revision} in {minutes} min {seconds} s",
        )
