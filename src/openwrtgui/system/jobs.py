"""The System screen's jobs (v0.6b D8, v0.6c D11, D12): reboot, restore and reset to defaults, one per
router. Each arms its step on the router under the write lock (audited), then waits for the router in the
background; the screen polls the job. A mixin of SystemService, so the job state and the clocks the tests
replace stay on that one object."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Collection, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited, run_audited_upload
from openwrtgui.net.apply import NetPlan, net_plan
from openwrtgui.paths import DataDir
from openwrtgui.store.routers import ReflashPending, RouterRecord, RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.archive import ArchiveInfo, read_archive, restore_refusals
from openwrtgui.system.backup import backup_dir, listing
from openwrtgui.system.parse import parse_board
from openwrtgui.system.reboot import (
    JobKind,
    RebootBusy,
    RebootJob,
    not_back,
    reboot_command,
    reboot_warnings,
)
from openwrtgui.system.restore import (
    FACTORY_ADDRESS,
    RESET_LIMIT_S,
    RestoreCheck,
    differing,
    listed_ok,
    not_reset,
    provable,
    reset_done,
    reset_warnings,
    restore_lines,
    restore_warnings,
    router_ipv4,
    wait_until_gone,
)
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.transport.comeback import Back, wait_for_reboot
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

SCREEN = "System"


class JobsMixin:
    # what SystemService gives these methods (set in its __init__)
    _pool: ConnectionPool
    _routers: RouterStore
    _guard: BenchGuard
    _audit: AuditLog
    _data: DataDir
    _clock: Callable[[], datetime]
    _sleep: Callable[[float], Awaitable[None]]
    _monotonic: Callable[[], float]
    _host_keys: HostKeyStore | None
    _app_keys: Callable[[RouterRecord], Collection[str]]
    _reboots: dict[str, RebootJob]
    _tasks: set[asyncio.Task[None]]
    every_s: float
    reboot_limit_s: float
    extra_busy: Callable[[str], str | None] | None  # a step-through holds the router (v0.7 D8)

    def _record(self, router_id: str) -> RouterRecord:
        raise NotImplementedError

    async def _stdout(self, t: Transport, command: str) -> str:
        raise NotImplementedError

    def backup_path(self, router_id: str, name: str) -> Path:
        raise NotImplementedError

    # ---------------------------------------------------------------- reboot (D8)
    async def plan_reboot(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[reboot_command()],
            warnings=reboot_warnings(rec.name),
        )

    def reboot_job(self, router_id: str) -> RebootJob | None:
        return self._reboots.get(router_id)

    def busy(self, router_id: str) -> str | None:
        """Why the router cannot be read now (a job holds it), for the live sampler; None when it can."""
        job = self._reboots.get(router_id)
        rec = self._routers.get(router_id)
        if job is None or rec is None or job.phase not in ("armed", "waiting"):
            return None
        doing = {"reboot": "is rebooting", "restore": "is restoring a backup", "reset": "is resetting"}
        return f"{rec.name} {doing[job.kind]}"

    def _not_busy(self, rec: RouterRecord) -> None:
        """No reboot, restore or reset while another job holds the router (a step-through, v0.7 D8)."""
        why = self.extra_busy(rec.id) if self.extra_busy is not None else None
        if why is not None:
            raise RebootBusy(why)

    def rebooting(self, router_id: str) -> bool:
        job = self._reboots.get(router_id)
        return job is not None and job.phase in ("armed", "waiting")

    async def _run(self, t: Transport, rec: RouterRecord, command: str, what: str) -> None:
        """One audited step of a job; a refusal is a ValueError naming the step."""
        done = await run_audited(
            t, command, router_id=rec.id, screen=SCREEN, guard=self._guard, audit=self._audit
        )
        if not done.ok:
            reason = (done.stderr or done.stdout).strip() or f"exit {done.exit_status}"
            raise ValueError(f"{rec.name} {what}: {reason}")

    async def _start(
        self,
        rec: RouterRecord,
        kind: JobKind,
        plan: NetPlan,
        digest: str,
        steps: Callable[[Transport], Awaitable[None]],
        wait: Callable[[RouterRecord, float], Coroutine[Any, Any, None]],
    ) -> RebootJob:
        """One job per router, whatever its kind: the check is under the write lock, so two starts at once
        never both arm (v0.6b minor). The steps run audited; the wait runs in the background."""
        busy = RebootBusy(f"{rec.name} is already rebooting")
        if self.rebooting(rec.id):  # at once: a running job holds the pool, so get() would wait for its end
            raise busy
        self._guard.require_clear()
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        t = await self._pool.get(rec)
        async with self._pool.write_lock(rec.id):
            if self.rebooting(rec.id):  # again under the lock: two starts at once never both arm
                raise busy
            await steps(t)
            armed_at = self._monotonic()
            job = RebootJob(router_id=rec.id, kind=kind, phase="armed", started_at=self._clock())
            self._reboots[rec.id] = job
        task = asyncio.create_task(wait(rec, armed_at))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def start_reboot(self, router_id: str, digest: str) -> RebootJob:
        """Arm the timer (audited, under the write lock), then wait for the router in the background."""
        rec = self._record(router_id)
        self._not_busy(rec)
        plan = await self.plan_reboot(rec.id)

        async def arm(t: Transport) -> None:
            await self._run(t, rec, plan.lines[0], "did not arm the reboot")

        return await self._start(rec, "reboot", plan, digest, arm, self._come_back)

    def _update_reboot(self, router_id: str, **fields: object) -> None:
        self._reboots[router_id] = self._reboots[router_id].model_copy(update=fields)

    async def _come_back(
        self,
        rec: RouterRecord,
        armed_at: float,
        prove: Callable[[Transport, float], Awaitable[list[str]]] | None = None,
    ) -> None:
        self._update_reboot(rec.id, phase="waiting")
        try:
            back: Back[list[str]] | None = await wait_for_reboot(
                self._pool,
                rec,
                armed_at=armed_at,
                clock=self._monotonic,
                sleep=self._sleep,
                every_s=self.every_s,
                limit_s=self.reboot_limit_s,
                prove=prove,
            )
        except Exception as exc:  # the job must end in a phase the screen shows, whatever broke
            log.exception("reboot of %s: the come-back wait failed", rec.id)
            self._update_reboot(rec.id, phase="not back", error=str(exc) or type(exc).__name__)
            return
        if back is None:
            self._update_reboot(rec.id, phase="not back", error=not_back(rec.name, self.reboot_limit_s))
            return
        detail = f"{rec.name} is back after {back.elapsed_s:.0f} s (uptime {back.uptime_s:.0f} s)"
        error = None
        if prove is not None:
            if back.proof:
                error = "These files differ from the backup: " + ", ".join(back.proof)
            else:
                detail += "; every restored file matches the backup"
        self._update_reboot(rec.id, phase="back", uptime_s=back.uptime_s, detail=detail, error=error)

    # ---------------------------------------------------------------- reset to defaults (D12, simulator only)
    async def plan_reset(self, router_id: str) -> NetPlan:
        rec = self._record(router_id)
        clash = next(
            (r.name for r in self._routers.list() if r.id != rec.id and r.host == FACTORY_ADDRESS), None
        )
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[s.firstboot_command()],
            warnings=reset_warnings(rec.name, clash),
        )

    async def start_reset(self, router_id: str, digest: str, confirm_name: str, alone: bool) -> RebootJob:
        """Only with the router's name typed and the "alone on this PC" tick; done when it stops answering,
        and its entry then waits for Add again (the flash-without-settings marker, reason reset)."""
        rec = self._record(router_id)
        self._not_busy(rec)
        if confirm_name != rec.name or not alone:
            raise ValueError(
                f"Type the router's name ({rec.name}) and tick that it is alone on this PC's network"
            )
        plan = await self.plan_reset(rec.id)
        identity: list[str] = []

        async def arm(t: Transport) -> None:
            board = parse_board(await self._stdout(t, s.BOARD))
            identity[:] = [(board.board_name or "") if board else "", (board.revision or "") if board else ""]
            await self._run(t, rec, plan.lines[0], "did not arm the reset")

        async def wait(r: RouterRecord, armed_at: float) -> None:
            self._update_reboot(r.id, phase="waiting")
            gone = await wait_until_gone(
                self._pool,
                r,
                armed_at=armed_at,
                clock=self._monotonic,
                sleep=self._sleep,
                every_s=self.every_s,
            )
            if not gone:
                self._update_reboot(r.id, phase="not reset", error=not_reset(r.name, RESET_LIMIT_S))
                return
            marker = ReflashPending(board=identity[0], revision=identity[1], at=self._clock(), reason="reset")
            current = self._routers.get(r.id)
            if current is not None:
                self._routers.upsert(current.model_copy(update={"reflashed": marker}))
            self._update_reboot(r.id, phase="reset", detail=reset_done(r.name))

        return await self._start(rec, "reset", plan, digest, arm, wait)

    # ---------------------------------------------------------------- restore (D11)
    def _restore_input(
        self, rec: RouterRecord, name: str, address: str
    ) -> tuple[bytes, ArchiveInfo, list[str]]:
        data = self.backup_path(rec.id, name).read_bytes()  # LookupError: not in the router's list
        info = read_archive(data)
        pinned = self._host_keys.get(rec.host, rec.port) if self._host_keys is not None else None
        refusals = restore_refusals(
            info,
            router_name=rec.name,
            address=address,
            port=rec.port,
            pinned=pinned,
            app=self._app_keys(rec),
        )
        return data, info, refusals

    def _created(self, rec: RouterRecord, name: str) -> datetime:
        return next(
            b.created_at for b in listing(backup_dir(self._data.root, rec.id), rec.id) if b.name == name
        )

    async def check_restore(self, router_id: str, name: str) -> RestoreCheck:
        rec = self._record(router_id)
        data, info, refusals = self._restore_input(rec, name, await router_ipv4(rec.host))
        return RestoreCheck(
            files=tuple(f.path for f in info.files),
            warnings=restore_warnings(rec.name, self._created(rec, name)),
            refusals=tuple(refusals),
        )

    def _restore_plan(self, rec: RouterRecord, name: str, address: str) -> tuple[NetPlan, bytes, ArchiveInfo]:
        data, info, refusals = self._restore_input(rec, name, address)
        if refusals:
            raise ValueError("Not restored: " + "; ".join(refusals))
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=restore_lines(name, data),
            warnings=restore_warnings(rec.name, self._created(rec, name)),
        )
        return plan, data, info

    async def plan_restore(self, router_id: str, name: str) -> NetPlan:
        rec = self._record(router_id)
        return self._restore_plan(rec, name, await router_ipv4(rec.host))[0]

    async def start_restore(self, router_id: str, name: str, digest: str) -> RebootJob:
        """Upload, list, restore, arm the reboot; then the come-back with the files proven. A step that
        fails removes the uploaded archive (it holds the router's secrets) and starts no job."""
        rec = self._record(router_id)
        self._not_busy(rec)
        plan, data, info = self._restore_plan(rec, name, await router_ipv4(rec.host))
        files = provable(info)

        async def steps(t: Transport) -> None:
            sent = await run_audited_upload(
                t,
                s.UPLOAD_RESTORE,
                data,
                name=name,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
            )
            if not sent.ok:
                raise ValueError(f"The backup did not reach {rec.name}: {(sent.stderr or '').strip()}")
            try:
                listed = await t.run(s.LIST_RESTORE)
                if not listed.ok or not listed_ok(listed.stdout, info):
                    raise ValueError(f"{rec.name} does not read the backup: {(listed.stderr or '').strip()}")
                await self._run(t, rec, s.RESTORE, "refused the restore")
                await self._run(t, rec, reboot_command(), "restored the files but did not arm the reboot")
            except (ValueError, TransportError):
                with contextlib.suppress(TransportError):
                    await run_audited(
                        t,
                        s.REMOVE_RESTORE,
                        router_id=rec.id,
                        screen=SCREEN,
                        guard=self._guard,
                        audit=self._audit,
                        require_guard=False,
                    )
                raise

        async def prove(t: Transport, uptime: float) -> list[str]:
            return await differing(t, files)

        async def wait(r: RouterRecord, armed_at: float) -> None:
            await self._come_back(r, armed_at, prove)

        return await self._start(rec, "restore", plan, digest, steps, wait)
