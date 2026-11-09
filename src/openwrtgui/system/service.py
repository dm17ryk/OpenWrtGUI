"""The System screen's service: reads, then settings, services, cron, diagnostics, reboot and backup."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.net.apply import (
    NOTHING,
    ApplyRunner,
    NetApplyResult,
    NetCheck,
    NetPlan,
    Planned,
    net_plan,
    saved_check,
)
from openwrtgui.paths import DataDir
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.system import commands as s
from openwrtgui.system.backup import BackupFile, backup_dir, backup_name, listing, save_archive
from openwrtgui.system.cron import CronState, check_crontab, has_tasks, read_tasks
from openwrtgui.system.parse import (
    Connection,
    RcService,
    parse_board,
    parse_conntrack,
    parse_rc_list,
    parse_timezones,
    parse_top,
)
from openwrtgui.system.reboot import (
    EVERY_S,
    LIMIT_S,
    RebootBusy,
    RebootJob,
    not_back,
    reboot_command,
    reboot_warnings,
)
from openwrtgui.system.services import (
    SETTLE_S,
    SystemServiceRow,
    action_holds,
    action_warnings,
    check_action,
    check_rc_local,
    service_rows,
)
from openwrtgui.system.settings import SystemSettings, current_settings, settings_ops
from openwrtgui.system.state import LogEntry, LogKind, ProcessList, SystemOverview, log_entries, read_overview
from openwrtgui.transport.base import Transport
from openwrtgui.transport.comeback import Back, wait_for_reboot
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.uci import parse_uci_show
from openwrtgui.wifi.service import PreviewChanged

log = logging.getLogger(__name__)

SCREEN = "System"
UTC = "UTC"
UTC_TZ = "GMT0"  # OpenWrt's own default for zonename UTC (AP2: zonename='UTC', timezone='GMT0')
NO_ZONES = "This router lists no time zones (LuCI's rpcd plugin is missing): only UTC can be chosen"


NO_CONNTRACK = "The connection table is not available: nf_conntrack is not loaded"
CRONTAB_FILE: s.FilePath = "/etc/crontabs/root"
DiagTool = Literal["ping", "traceroute", "nslookup"]
_DIAG: dict[str, Callable[[str], str]] = {"ping": s.ping, "traceroute": s.traceroute, "nslookup": s.nslookup}
DIAG_TIMEOUT_S = s.DIAG_LIMIT_S + 5.0  # the router's own `timeout -s KILL` ends it first


class DiagResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: DiagTool
    target: str
    command: str
    output: str  # stdout, then stderr: a bad address is a result, not an error
    exit_status: int


class Connections(BaseModel):
    model_config = ConfigDict(frozen=True)

    rows: list[Connection]  # at most 500 (AP2 has ~7 MB free RAM)
    note: str | None = None


class TimeZones(BaseModel):
    model_config = ConfigDict(frozen=True)

    zones: list[str]  # UTC first (the router's list has none: LuCI adds it), then the router's, sorted
    note: str | None = None


async def file_check(t: Transport, read: str, wanted: str) -> NetCheck:
    """`saved`: the file read back is exactly what was sent."""
    result = await t.run(read)
    if result.ok and result.stdout == wanted:
        return NetCheck("saved", True, "the router has the new file")
    return NetCheck("saved", False, "the file read back differs" if result.ok else "the file does not read")


class SystemService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        runner: ApplyRunner,
        data: DataDir,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._runner = runner
        self._data = data
        self._clock = clock
        self._sleep = sleep
        self._monotonic = monotonic
        self.every_s = EVERY_S  # how often the come-back wait asks
        self.reboot_limit_s = LIMIT_S
        self._reboots: dict[str, RebootJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _transport(self, router_id: str) -> tuple[RouterRecord, Transport]:
        rec = self._record(router_id)
        return rec, await self._pool.get(rec)

    async def _stdout(self, t: Transport, command: str) -> str:
        result = await t.run(command)
        return result.stdout if result.ok else ""

    # ---------------------------------------------------------------- reads (they work during a run)
    async def overview(self, router_id: str) -> SystemOverview:
        rec, t = await self._transport(router_id)
        return await read_overview(t, router_id=rec.id, now=self._clock())

    async def logs(self, router_id: str, kind: LogKind, lines: s.LogLength) -> list[LogEntry]:
        read = s.logread(lines)  # checks the length for both logs
        command = read if kind == "system" else s.DMESG
        _rec, t = await self._transport(router_id)
        entries = log_entries(await self._stdout(t, command), kind)
        return entries if kind == "system" else entries[-lines:]

    async def processes(self, router_id: str) -> ProcessList:
        _rec, t = await self._transport(router_id)
        rows, cpu, column = parse_top(await self._stdout(t, s.TOP))
        return ProcessList(rows=rows, cpu=cpu, column=column)

    async def services(self, router_id: str) -> list[SystemServiceRow]:
        _rec, t = await self._transport(router_id)
        return service_rows(parse_rc_list(await self._stdout(t, s.RC_LIST)))

    async def connections(self, router_id: str) -> Connections:
        _rec, t = await self._transport(router_id)
        result = await t.run(s.CONNTRACK)
        if not result.ok:
            return Connections(rows=[], note=NO_CONNTRACK)
        return Connections(rows=parse_conntrack(result.stdout))

    # ---------------------------------------------------------------- diagnostics (D4)
    async def diagnose(self, router_id: str, tool: DiagTool, target: str) -> DiagResult:
        """Run on the router, no preview, audited; refused during a run (traffic from a router under test)."""
        if tool not in _DIAG:
            raise ValueError(f"{tool!r} is not one of {', '.join(_DIAG)}")
        command = _DIAG[tool](target)  # checks the target before anything is sent
        self._guard.require_clear()
        rec, t = await self._transport(router_id)
        done = await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            timeout=DIAG_TIMEOUT_S,
        )
        output = done.stdout + (done.stderr if done.stderr else "")
        return DiagResult(
            tool=tool, target=target, command=command, output=output, exit_status=done.exit_status
        )

    async def _zones(self, t: Transport) -> dict[str, str]:
        return {UTC: UTC_TZ} | parse_timezones(await self._stdout(t, s.TIMEZONES))

    async def zone_strings(self, router_id: str) -> dict[str, str]:
        """Zone name -> TZ string, the router's list plus UTC."""
        _rec, t = await self._transport(router_id)
        return await self._zones(t)

    # ---------------------------------------------------------------- system and time (D5)
    async def _uci(self, t: Transport) -> dict[str, str]:
        result = await t.run(s.UCI_SYSTEM)
        if not result.ok:
            raise ValueError(
                f"The router's system config does not read: {result.stderr.strip() or result.exit_status}"
            )
        return parse_uci_show(result.stdout)

    async def settings(self, router_id: str) -> SystemSettings:
        _rec, t = await self._transport(router_id)
        return current_settings(await self._uci(t))

    async def _settings_plan(
        self, rec: RouterRecord, t: Transport, req: SystemSettings
    ) -> tuple[NetPlan, dict[str, str], dict[str, str]]:
        uci = await self._uci(t)
        zones = await self._zones(t) if req.zonename is not None else {}
        ops, reloads = settings_ops(uci, req, zones)
        plan = net_plan(
            router_id=rec.id, screen=SCREEN, config="system", ops=ops, current=uci, reloads=reloads
        )
        return plan, uci, zones

    async def plan_settings(self, router_id: str, req: SystemSettings) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._settings_plan(rec, t, req))[0]

    async def apply_settings(self, router_id: str, req: SystemSettings, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, uci, zones = await self._settings_plan(rec, t, req)

            async def verify(t2: Transport) -> list[NetCheck]:
                checks = [await saved_check(t2, s.UCI_SYSTEM, plan.ops, uci)]
                if req.hostname is not None:
                    board = parse_board(await self._stdout(t2, s.BOARD))
                    live = board.hostname if board else None
                    checks.append(NetCheck("hostname", live == req.hostname, live or "no answer"))
                if req.zonename is not None:
                    tz = (await self._stdout(t2, s.TZ_FILE)).strip()
                    checks.append(NetCheck("time zone", tz == zones[req.zonename], tz or "no answer"))
                return checks

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- services and rc.local (D6, D7)
    async def _rc_row(self, t: Transport, name: str) -> RcService | None:
        return next((r for r in parse_rc_list(await self._stdout(t, s.RC_LIST)) if r.name == name), None)

    async def _service_plan(
        self, rec: RouterRecord, t: Transport, name: str, action: s.ServiceAction
    ) -> NetPlan:
        s.init(name, action)  # the name and action first: nothing odd reaches the router
        command = check_action(await self._rc_row(t, name), name, action, rec.name)
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[command],
            warnings=action_warnings(name, action, rec.name),
        )

    async def plan_service(self, router_id: str, name: str, action: s.ServiceAction) -> NetPlan:
        rec, t = await self._transport(router_id)
        return await self._service_plan(rec, t, name, action)

    async def apply_service(
        self, router_id: str, name: str, action: s.ServiceAction, digest: str | None
    ) -> NetApplyResult:
        """Proof: `rc list` shows the new state within SETTLE_S (a one-shot: its exit status)."""
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan = await self._service_plan(rec, t, name, action)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await self._settled(t2, name, action, f"service {name}")]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    async def _settled(self, t: Transport, name: str, action: s.ServiceAction, check: str) -> NetCheck:
        """`rc list` re-read each second until it shows what the action does, SETTLE_S at most."""
        waited = 0.0
        while True:
            ok, detail = action_holds(await self._rc_row(t, name), action)
            if ok or waited >= SETTLE_S:
                break
            await self._sleep(1.0)
            waited += 1.0
        return NetCheck(check, ok, detail if ok else f"{detail} after {SETTLE_S:g} s")

    async def rc_local(self, router_id: str) -> str:
        """The file as the router has it; "" when there is none."""
        _rec, t = await self._transport(router_id)
        return await self._stdout(t, s.RC_LOCAL)

    async def _rc_local_plan(self, rec: RouterRecord, t: Transport, text: str) -> tuple[NetPlan, str]:
        wanted = check_rc_local(text)
        command = s.write_file("/etc/rc.local", wanted)  # OWG and size refused before anything is sent
        if await self._stdout(t, s.RC_LOCAL) == wanted:
            raise ValueError(NOTHING)
        plan = net_plan(router_id=rec.id, screen=SCREEN, config=None, ops=[], current={}, commands=[command])
        return plan, wanted

    async def plan_rc_local(self, router_id: str, text: str) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._rc_local_plan(rec, t, text))[0]

    async def apply_rc_local(self, router_id: str, text: str, digest: str | None) -> NetApplyResult:
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, wanted = await self._rc_local_plan(rec, t, text)

            async def verify(t2: Transport) -> list[NetCheck]:
                return [await file_check(t2, s.RC_LOCAL, wanted)]

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

    # ---------------------------------------------------------------- scheduled tasks (D7)
    async def crontab(self, router_id: str) -> CronState:
        _rec, t = await self._transport(router_id)
        text = await self._stdout(t, s.CRONTAB)
        row = await self._rc_row(t, "cron")
        tasks, note = read_tasks(text)
        return CronState(
            text=text,
            tasks=tasks,
            cron_enabled=row is not None and row.enabled,
            cron_running=row is not None and row.running,
            note=note,
        )

    async def _crontab_plan(self, rec: RouterRecord, t: Transport, text: str) -> tuple[NetPlan, str, bool]:
        """(plan, the file as it reads back, whether cron must run): the write, `cron enable` only when
        disabled, then `cron restart`."""
        wanted = check_crontab(text)
        command = s.write_file(CRONTAB_FILE, wanted)  # OWG and size refused before anything is sent
        expected = wanted or "\n"  # the heredoc writes at least its one (empty) line
        current = await self._stdout(t, s.CRONTAB)
        if current == expected or (not wanted.strip() and not current.strip()):
            raise ValueError(NOTHING)
        row = await self._rc_row(t, "cron")
        enable = [s.init("cron", "enable")] if row is not None and not row.enabled else []
        plan = net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=[command, *enable],
            reloads=[s.init("cron", "restart")],
        )
        return plan, expected, has_tasks(wanted)

    async def plan_crontab(self, router_id: str, text: str) -> NetPlan:
        rec, t = await self._transport(router_id)
        return (await self._crontab_plan(rec, t, text))[0]

    async def apply_crontab(self, router_id: str, text: str, digest: str | None) -> NetApplyResult:
        """Proof: the file reads back as sent, and cron runs once there is a task (it idles without)."""
        rec = self._record(router_id)

        async def make(t: Transport) -> Planned:
            plan, expected, tasks = await self._crontab_plan(rec, t, text)

            async def verify(t2: Transport) -> list[NetCheck]:
                checks = [await file_check(t2, s.CRONTAB, expected)]
                if tasks:
                    checks.append(await self._settled(t2, "cron", "start", "cron"))
                return checks

            return Planned(plan, verify)

        return await self._runner.run_planned(rec, make, digest)

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

    def rebooting(self, router_id: str) -> bool:
        job = self._reboots.get(router_id)
        return job is not None and job.phase in ("armed", "waiting")

    async def start_reboot(self, router_id: str, digest: str) -> RebootJob:
        """Arm the timer (audited, under the write lock), then wait for the router in the background."""
        rec = self._record(router_id)
        if self.rebooting(rec.id):
            raise RebootBusy(f"{rec.name} is already rebooting")
        self._guard.require_clear()
        plan = await self.plan_reboot(rec.id)
        if plan.digest != digest:
            raise PreviewChanged(rec.name)
        t = await self._pool.get(rec)
        async with self._pool.write_lock(rec.id):
            armed = await run_audited(
                t, plan.lines[0], router_id=rec.id, screen=SCREEN, guard=self._guard, audit=self._audit
            )
        if not armed.ok:
            reason = (armed.stderr or armed.stdout).strip() or f"exit {armed.exit_status}"
            raise ValueError(f"{rec.name} did not arm the reboot: {reason}")
        armed_at = self._monotonic()
        job = RebootJob(router_id=rec.id, phase="armed", started_at=self._clock())
        self._reboots[rec.id] = job
        task = asyncio.create_task(self._come_back(rec, armed_at))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def _update_reboot(self, router_id: str, **fields: object) -> None:
        self._reboots[router_id] = self._reboots[router_id].model_copy(update=fields)

    async def _come_back(self, rec: RouterRecord, armed_at: float) -> None:
        self._update_reboot(rec.id, phase="waiting")
        try:
            back: Back[None] | None = await wait_for_reboot(
                self._pool,
                rec,
                armed_at=armed_at,
                clock=self._monotonic,
                sleep=self._sleep,
                every_s=self.every_s,
                limit_s=self.reboot_limit_s,
            )
        except Exception as exc:  # the job must end in a phase the screen shows, whatever broke
            log.exception("reboot of %s: the come-back wait failed", rec.id)
            self._update_reboot(rec.id, phase="not back", error=str(exc) or type(exc).__name__)
            return
        if back is None:
            self._update_reboot(rec.id, phase="not back", error=not_back(rec.name, self.reboot_limit_s))
            return
        self._update_reboot(
            rec.id,
            phase="back",
            uptime_s=back.uptime_s,
            detail=f"{rec.name} is back after {back.elapsed_s:.0f} s (uptime {back.uptime_s:.0f} s)",
        )

    # ---------------------------------------------------------------- backup (D9)
    async def create_backup(self, router_id: str) -> BackupFile:
        """Allowed during a run: it changes nothing on the router. One audit line names the file."""
        rec, t = await self._transport(router_id)
        name = backup_name(rec.id, self._clock())
        path = backup_dir(self._data.root, rec.id) / name
        if path.exists():
            raise ValueError(f"A backup of {rec.name} was saved this second already")
        total, status, problem = await save_archive(t, path)
        self._audit.record(
            router=rec.id,
            screen=SCREEN,
            command=f"{s.BACKUP}  # saved to {name}"
            if not problem
            else f"{s.BACKUP}  # not saved: {problem}",
            exit_status=status,
            source="user",
        )
        if problem:
            raise ValueError(f"{rec.name} gave no backup: {problem}")
        return BackupFile(name=name, size=total, created_at=self._clock().astimezone())

    async def backups(self, router_id: str) -> list[BackupFile]:
        rec = self._record(router_id)
        return listing(backup_dir(self._data.root, rec.id))

    def backup_path(self, router_id: str, name: str) -> Path:
        """Only a name the listing shows: nothing else under the data folder is served."""
        rec = self._record(router_id)
        folder = backup_dir(self._data.root, rec.id)
        if name not in {b.name for b in listing(folder)}:
            raise LookupError(f"No backup {name} of {rec.name}")
        return folder / name

    async def timezones(self, router_id: str) -> TimeZones:
        zones = await self.zone_strings(router_id)
        names = [UTC, *sorted(name for name in zones if name != UTC)]
        return TimeZones(zones=names, note=NO_ZONES if len(names) == 1 else None)
