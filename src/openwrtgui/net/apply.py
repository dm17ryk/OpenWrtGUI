"""Applying a network-screen change (plan v0.3, "Two ways to apply").

Plain: one script (`set -e`, the uci lines, `uci commit <config>`), the runtime commands, the reloads.
With rollback (every `network` change): the changes are staged in an rpcd session and applied with
`ubus call uci apply` and a 60 s rollback, the way LuCI applies them. The app then reconnects, at the new
address when lan's address changed, and confirms; if it cannot, rpcd restores the previous settings by
itself and the app checks they are back (O14, proven on AP2 2026-11-05).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets as tokens
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openwrtgui.guard.audit import AuditLog, Source, mask
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited
from openwrtgui.luci_bridge.session import create_command, destroy_command
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.timer import TIMER_DIR, arm_command, cancel_command
from openwrtgui.transport.base import (
    CommandResult,
    HostKeyChanged,
    HostKeyInfo,
    HostKeyUnknown,
    Transport,
    TransportError,
    ubus_call,
    ubus_command,
)
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore, fetch_host_key
from openwrtgui.uci import UciOp, drop_unchanged, order_for_script, parse_uci_show, render_uci
from openwrtgui.wifi.service import PreviewChanged

ROLLBACK_S = 60
RECONNECT_WINDOW_S = 40.0
RECONNECT_EVERY_S = 2.0
SETTLE_S = 5.0  # before the first reconnect; LuCI holds off 4 s (apply_holdoff)
RESTORE_CHECK_S = 65.0
RESTORE_RETRY_S = 20.0  # the router may still be coming back at 65 s
SCRIPT_TIMEOUT_S = 60.0
SERVICE_WAIT_S = 10.0
SESSION = "<session>"
ROLLBACK_ID = "<rollback>"  # the router-side rollback timer's id in a preview; a fresh one at apply
NOTHING = "Nothing to apply: the router already has these settings."
_ANONYMOUS = re.compile(r"cfg[0-9a-f]{6}")  # libuci's name for an unnamed section


@dataclass(frozen=True)
class NetCheck:
    name: str
    ok: bool | None
    detail: str


@dataclass(frozen=True)
class NetPlan:
    router_id: str
    screen: str
    config: str | None
    lines: tuple[str, ...]
    ops: tuple[UciOp, ...] = field(repr=False)
    commands: tuple[str, ...]
    reloads: tuple[str, ...]
    rollback: bool
    target_host: str | None
    warnings: tuple[str, ...]
    secrets: tuple[str, ...] = field(repr=False)
    # A change outside uci rolls back by a router-side timer: `backup` runs before it is armed, `restore` is
    # what the timer runs if the app does not cancel it (both may name /tmp/owg/rb-<rollback>.* files).
    backup: tuple[str, ...] = ()
    restore: tuple[str, ...] = ()

    @property
    def timer(self) -> bool:
        return self.rollback and bool(self.restore)

    @property
    def digest(self) -> str:
        """Names the preview: Apply sends it back, so only the lines the user saw ever run."""
        return hashlib.sha256("\n".join(self.lines).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class NetApplyResult:
    router_id: str
    applied: bool
    verified: bool
    checks: tuple[NetCheck, ...]
    error: str | None
    host: str | None


Verifier = Callable[[Transport], Awaitable[list[NetCheck]]]


@dataclass(frozen=True)
class Snapshot:
    """What the router held before the change: read back with `command` after a rollback to prove it."""

    command: str
    before: Mapping[str, str]
    parse: Callable[[str], dict[str, str]] = parse_uci_show


@dataclass(frozen=True)
class Planned:
    plan: NetPlan
    verify: Verifier
    snapshot: Snapshot | None = None


Planner = Callable[[Transport], Awaitable[Planned]]


def savedir(sid: str) -> str:
    return f"/var/run/rpcd/uci-{sid}"


def session_commands(sid: str, config: str) -> tuple[str, str, str, str, str]:
    """create, grant, apply, confirm, destroy for one rpcd session."""
    grant = {"objects": [[config, "read"], [config, "write"]], "scope": "uci", "ubus_rpc_session": sid}
    return (
        create_command(),
        ubus_command("session", "grant", grant),
        ubus_command("uci", "apply", {"rollback": True, "timeout": ROLLBACK_S, "ubus_rpc_session": sid}),
        ubus_command("uci", "confirm", {"ubus_rpc_session": sid}),
        destroy_command(sid),
    )


def _script(ops: Sequence[UciOp], config: str | None, sid: str | None) -> str:
    if sid is not None:
        return "\n".join(["set -e", f"mkdir -p {savedir(sid)}", *render_uci(ops, savedir(sid))])
    return "\n".join(["set -e", *render_uci(ops), *([f"uci commit {config}"] if config else [])])


def _timer_name(rid: str) -> str:
    return f"rb-{rid}"


def timer_lines(backup: Sequence[str], restore: Sequence[str], rid: str) -> tuple[str, str]:
    """The exec that backs up and arms the rollback timer, and the line that cancels it (the confirm)."""
    name = _timer_name("000000")  # a valid timer name, then the id goes in
    restore = [line.replace(ROLLBACK_ID, rid) for line in restore]
    arm = arm_command(name, ROLLBACK_S, restore).replace(name, _timer_name(rid))
    cancel = f"{cancel_command(name)}; rm -f {TIMER_DIR}/{name}*".replace(name, _timer_name(rid))
    return "\n".join(["set -e", *(line.replace(ROLLBACK_ID, rid) for line in backup), arm]), cancel


def rollback_warning(router_name: str, target: str, what: str = "network settings") -> str:
    return (
        f"Applies with a {ROLLBACK_S} s rollback: if the app cannot reach {router_name} at {target} again "
        f"and confirm, the router restores its previous {what} by itself."
    )


def net_plan(
    *,
    router_id: str,
    screen: str,
    config: str | None,
    ops: Sequence[UciOp],
    current: Mapping[str, str],
    commands: Sequence[str] = (),
    reloads: Sequence[str] = (),
    rollback: bool = False,
    target_host: str | None = None,
    warnings: Sequence[str] = (),
    secrets: Sequence[str] = (),
    backup: Sequence[str] = (),
    restore: Sequence[str] = (),
) -> NetPlan:
    """The exact preview: only changes, section deletes last; nothing left is refused with NOTHING."""
    kept = order_for_script(drop_unchanged(ops, current), current)
    if not kept and not commands:
        raise ValueError(NOTHING)
    shown = [line for command in commands for line in command.splitlines()]  # a heredoc, line by line
    if rollback and restore:
        armed, cancel = timer_lines(backup, restore, ROLLBACK_ID)
        script = _script(kept, config, None).splitlines() if kept else []
        lines = [*armed.splitlines(), *script, *shown, cancel]
    elif rollback:
        if config is None:
            raise ValueError("a rollback change names its config")
        create, grant, apply, confirm, destroy = session_commands(SESSION, config)
        script = _script(kept, config, SESSION).splitlines()
        lines = [create, grant, *script, apply, *shown, confirm, destroy]
    else:
        lines = [*(_script(kept, config, None).splitlines() if kept else []), *shown, *reloads]
    return NetPlan(
        router_id=router_id,
        screen=screen,
        config=config,
        lines=tuple(mask(line, secrets) for line in lines),
        ops=tuple(kept),
        commands=tuple(commands),
        reloads=tuple(reloads),
        rollback=rollback,
        target_host=target_host,
        warnings=tuple(warnings),
        secrets=tuple(secrets),
        backup=tuple(backup),
        restore=tuple(restore),
    )


def _settings(plan: NetPlan) -> str:
    """What a rollback puts back, in the result's words."""
    return {"network": "network settings", "firewall": "firewall settings"}.get(plan.config or "", "settings")


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _holds(op: UciOp, shown: Mapping[str, str]) -> bool:
    if op.op == "add":
        return True
    if "$" in op.path:  # an option of a section the script made: some section of the config has it
        config, option = op.path.split(".", 1)[0], op.path.rsplit(".", 1)[-1]
        return op.op == "delete" or any(
            k.startswith(config + ".")
            and k.endswith("." + option)
            and (op.value in v.split() if op.op == "add_list" else v == op.value)
            for k, v in shown.items()
        )
    items = shown.get(op.path, "").split()
    if op.op == "set":
        return shown.get(op.path) == op.value
    if op.op == "delete":
        return op.path not in shown
    if op.op == "add_list":
        return op.value in items
    return op.value not in items  # del_list


def _sections(shown: Mapping[str, str], config: str) -> dict[str, tuple[str, dict[str, str]]]:
    """{section: (type, {option: value})} of one config in a `uci -X show` map."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for key, value in shown.items():
        parts = key.split(".")
        if parts[0] != config or len(parts) not in (2, 3):
            continue
        type_, options = out.get(parts[1], ("", {}))
        if len(parts) == 2:
            out[parts[1]] = (value, options)
        else:
            out[parts[1]] = (type_, {**options, parts[2]: value})
    return out


def _after(options: Mapping[str, str], ops: Sequence[UciOp]) -> dict[str, str] | None:
    """A section's options once `ops` ran on it; None when they delete it."""
    now = dict(options)
    for op in ops:
        name = op.path.split(".")[2] if op.path.count(".") == 2 else None
        if name is None:
            if op.op == "delete":
                return None
            continue
        items = now.get(name, "").split()
        if op.op == "set":
            now[name] = op.value or ""
        elif op.op == "delete":
            now.pop(name, None)
        elif op.op == "add_list":
            now[name] = " ".join([*items, op.value or ""])
        else:  # del_list
            kept = [i for i in items if i != op.value]
            if kept:
                now[name] = " ".join(kept)
            else:
                now.pop(name, None)
    return now


async def saved_check(
    t: Transport, show_command: str, ops: Sequence[UciOp], before: Mapping[str, str] | None = None
) -> NetCheck:
    """`saved`: the config read back holds every change of the plan.

    An anonymous section (`cfg<n><hash>`) is found by its content: libuci names it from its type and
    options each time it loads the config, so after the commit an edited one has another name. `before`
    is the config the plan was made from."""
    shown = parse_uci_show((await t.run(show_command)).stdout)
    by_section: dict[tuple[str, str], list[UciOp]] = {}
    rest: list[UciOp] = []
    for op in ops:
        parts = op.path.split(".")
        anonymous = len(parts) >= 2 and _ANONYMOUS.fullmatch(parts[1]) is not None
        if before is not None and anonymous and f"{parts[0]}.{parts[1]}" in before:
            by_section.setdefault((parts[0], parts[1]), []).append(op)
            continue
        rest.append(op)
    wrong = [op.path for op in rest if not _holds(op, shown)]
    for (config, section), section_ops in by_section.items():
        assert before is not None
        type_, options = _sections(before, config)[section]
        want = _after(options, section_ops)
        now = [o for t_, o in _sections(shown, config).values() if t_ == type_]
        if (want is None and options in now) or (want is not None and want not in now):
            wrong.append(f"{config}.{section}")
    if wrong:
        return NetCheck("saved", False, "not as asked: " + ", ".join(wrong))
    return NetCheck("saved", True, "the router has the change")


async def service_check(
    t: Transport,
    name: str,
    *,
    wait_s: float = SERVICE_WAIT_S,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> NetCheck:
    """`<service>`: procd has a running instance of it, polled for a few seconds: a reload restarts it,
    under a new instance name when libuci named its section anew (AP2, 2026-11-06)."""
    for attempt in range(int(wait_s) + 1):
        if attempt:
            await sleep(1.0)
        listed = await ubus_call(t, "service", "list", {"name": name}) or {}
        instances = listed.get(name, {}).get("instances", {})
        if any(isinstance(i, dict) and i.get("running") for i in instances.values()):
            return NetCheck(name, True, "running")
    return NetCheck(name, False, f"{name} is not running")


class ApplyRunner:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        host_keys: HostKeyStore,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        rollback_s: float = ROLLBACK_S,
        window_s: float = RECONNECT_WINDOW_S,
        every_s: float = RECONNECT_EVERY_S,
        restore_s: float = RESTORE_CHECK_S,
        fetch_key: Callable[..., Awaitable[HostKeyInfo]] = fetch_host_key,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._host_keys = host_keys
        self._clock = clock
        self._sleep = sleep
        self._rollback_s = rollback_s
        self._window_s = window_s
        self._every_s = every_s
        self._restore_s = restore_s
        self._fetch_key = fetch_key
        self._holds: dict[str, object] = {}  # router id -> the pool hold a rollback apply has

    async def _run(
        self, t: Transport, rec: RouterRecord, plan: NetPlan, command: str, source: Source = "user", **kw: Any
    ) -> CommandResult:
        return await run_audited(
            t,
            command,
            router_id=rec.id,
            screen=plan.screen,
            guard=self._guard,
            audit=self._audit,
            source=source,
            **kw,
        )

    def _finish(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        applied: bool,
        checks: Sequence[NetCheck],
        error: str | None,
        host: str,
    ) -> NetApplyResult:
        failed = [c.name for c in checks if c.ok is False]
        verified = applied and bool(checks) and not failed and all(c.ok for c in checks)
        if checks:
            self._audit.record(
                router=rec.id,
                screen=plan.screen,
                command=f"verify {plan.config or plan.screen.lower()}",
                exit_status=None,
                verify="pass" if verified else f"fail: {', '.join(failed) or 'not run'}",
                source="app",
            )
        return NetApplyResult(rec.id, applied, verified, tuple(checks), error, host)

    async def run_planned(
        self, rec: RouterRecord, make: Planner, digest: str | None, *, guarded: bool = True
    ) -> NetApplyResult:
        """Plan and apply under the router's write lock: a change made between the preview's digest check and
        the lock would otherwise slip through. A digest that differs sends nothing (PreviewChanged).
        `guarded=False` only for a plain change that undoes what the app set up (clearing faults)."""
        if guarded:
            self._guard.require_clear()
        async with self._pool.write_lock(rec.id):
            t = await self._pool.get(rec)
            planned = await make(t)
            if digest is not None and digest != planned.plan.digest:
                raise PreviewChanged(rec.name)
            return await self.run_locked(rec, t, planned, guarded=guarded)

    async def run_locked(
        self, rec: RouterRecord, t: Transport, planned: Planned, *, guarded: bool = True
    ) -> NetApplyResult:
        """The apply itself; the caller holds the router's write lock and checked the digest."""
        if planned.plan.rollback:
            assert guarded, "a rollback change is always checked by Bench Guard"
            return await self._with_rollback(rec, t, planned.plan, planned.verify, planned.snapshot)
        return await self._plain(rec, t, planned.plan, planned.verify, guarded)

    # ------------------------------------------------------------------ plain
    async def _plain(
        self, rec: RouterRecord, t: Transport, plan: NetPlan, verify: Verifier, guarded: bool = True
    ) -> NetApplyResult:
        applied = False
        try:
            if plan.ops:
                try:
                    done = await self._run(
                        t,
                        rec,
                        plan,
                        _script(plan.ops, plan.config, None),
                        secrets=plan.secrets,
                        timeout=SCRIPT_TIMEOUT_S,
                        require_guard=guarded,
                    )
                except TransportError as exc:
                    lost = (
                        f"Lost the connection to {rec.name} while the change ran; it may have been committed"
                    )
                    return self._finish(rec, plan, False, (), f"{lost}: {exc}", rec.host)
                if not done.ok:
                    return self._finish(
                        rec, plan, False, (), f"The router refused the change: {_reason(done)}", rec.host
                    )
                applied = True
            for command in plan.commands:
                done = await self._run(
                    t,
                    rec,
                    plan,
                    command,
                    secrets=plan.secrets,
                    timeout=SCRIPT_TIMEOUT_S,
                    require_guard=guarded,
                )
                if not done.ok:
                    return self._finish(
                        rec, plan, applied, (), f"{command} failed: {_reason(done)}", rec.host
                    )
                applied = True
            error: str | None = None
            for reload in plan.reloads:
                # the change is committed: a run that starts now must not leave it saved but not in effect
                done = await self._run(t, rec, plan, reload, timeout=SCRIPT_TIMEOUT_S, require_guard=False)
                if not done.ok:
                    error = f"The reload failed after the change was saved: {_reason(done)}"
            state = self._guard.state()
            if error is None and plan.reloads and state.live:
                run = state.reasons[0].text if state.reasons else "a harness run"
                error = f"Saved and reloaded although Bench Guard went live ({run})"
            return self._finish(rec, plan, applied, await verify(t), error, rec.host)
        except GuardLocked as exc:
            if not applied:
                raise
            return self._finish(rec, plan, True, (), f"Applied, not verified: {exc}", rec.host)
        except TransportError as exc:
            return self._finish(rec, plan, applied, (), f"Applied, not verified: {exc}", rec.host)

    # ------------------------------------------------------------------ with rollback
    async def _with_rollback(
        self,
        rec: RouterRecord,
        t: Transport,
        plan: NetPlan,
        verify: Verifier,
        snapshot: Snapshot | None,
    ) -> NetApplyResult:
        async with self._pool.hold(rec.id) as token:
            self._holds[rec.id] = token
            try:
                if plan.timer:
                    return await self._timer_rollback(rec, t, plan, verify, snapshot)
                return await self._rpcd_rollback(rec, t, plan, verify, snapshot)
            finally:
                del self._holds[rec.id]

    async def _timer_rollback(
        self,
        rec: RouterRecord,
        t: Transport,
        plan: NetPlan,
        verify: Verifier,
        snapshot: Snapshot | None,
    ) -> NetApplyResult:
        """A change outside uci: back up, arm a router-side timer that restores the backup, change, then
        reconnect and cancel the timer once the change is seen in effect."""
        rid = tokens.token_hex(3)
        armed, cancel = timer_lines(plan.backup, plan.restore, rid)
        try:
            done = await self._run(t, rec, plan, armed, source="app", timeout=SCRIPT_TIMEOUT_S)
        except TransportError as exc:
            error = f"Lost the connection to {rec.name} before the change was applied: {exc}"
            return self._finish(rec, plan, False, (), error, rec.host)
        if not done.ok:
            error = f"Could not arm the rollback timer on {rec.name}: {_reason(done)}"
            return self._finish(rec, plan, False, (), error, rec.host)
        try:
            steps = [_script(plan.ops, plan.config, None)] if plan.ops else []
            for command in [*steps, *(c.replace(ROLLBACK_ID, rid) for c in plan.commands)]:
                done = await self._run(t, rec, plan, command, secrets=plan.secrets, timeout=SCRIPT_TIMEOUT_S)
                if not done.ok:  # put the previous state back now, not in 60 s
                    restore = "; ".join(plan.restore).replace(ROLLBACK_ID, rid)
                    await self._run(t, rec, plan, restore, source="app", require_guard=False)
                    await self._run(t, rec, plan, cancel, source="app", require_guard=False)
                    error = f"The router refused the change: {_reason(done)}"
                    return self._finish(rec, plan, False, (), error, rec.host)
        except TransportError:
            pass  # the change may have cut this connection: reconnect and confirm decides
        return await self._settle(rec, plan, verify, snapshot, cancel, None)

    async def _rpcd_rollback(
        self,
        rec: RouterRecord,
        t: Transport,
        plan: NetPlan,
        verify: Verifier,
        snapshot: Snapshot | None,
    ) -> NetApplyResult:
        assert plan.config is not None
        created = await self._run(t, rec, plan, create_command(), source="app")
        sid = str(json.loads(created.stdout)["ubus_rpc_session"])
        _, grant, apply, confirm, destroy = session_commands(sid, plan.config)
        try:
            await self._run(t, rec, plan, grant, source="app")
            staged = await self._run(
                t,
                rec,
                plan,
                _script(plan.ops, plan.config, sid),
                secrets=plan.secrets,
                timeout=SCRIPT_TIMEOUT_S,
            )
            if not staged.ok:
                await self._run(t, rec, plan, destroy, source="app", require_guard=False)
                return self._finish(
                    rec, plan, False, (), f"The router refused the change: {_reason(staged)}", rec.host
                )
        except TransportError as exc:
            error = f"Lost the connection to {rec.name} before the change was applied: {exc}"
            return self._finish(rec, plan, False, (), error, rec.host)
        try:
            done = await self._run(t, rec, plan, apply)
            if not done.ok:
                await self._run(t, rec, plan, destroy, source="app", require_guard=False)
                return self._finish(
                    rec, plan, False, (), f"The router refused the change: {_reason(done)}", rec.host
                )
            for command in plan.commands:
                await self._run(t, rec, plan, command, secrets=plan.secrets)
        except TransportError:
            pass  # the change may have cut this connection: reconnect and confirm decides
        return await self._settle(rec, plan, verify, snapshot, confirm, destroy)

    async def _settle(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        verify: Verifier,
        snapshot: Snapshot | None,
        confirm: str,
        destroy: str | None,
    ) -> NetApplyResult:
        """After the change: reconnect, see it in effect, confirm; or report the rollback."""
        applied_at = self._clock()
        target = plan.target_host or rec.host
        t2, why = await self._reconnect(rec, target, applied_at, SETTLE_S)
        while t2 is not None:
            # Confirm only once the change is seen in effect over the new connection (the verifier polls
            # for it): procd reloads a few seconds after `uci apply`, and a confirm sent before that would
            # cancel the rollback of a change that then cuts the app off.
            try:
                checks = await verify(t2)
            except TransportError:  # the change took effect and cut this connection
                t2, why = await self._reconnect(rec, target, applied_at, self._every_s)
                continue
            if any(c.ok is False for c in checks):  # not seen in effect: the router keeps nothing that failed
                return await self._unproven(rec, plan, target, checks, applied_at, snapshot)
            return await self._confirm(rec, plan, t2, target, confirm, destroy, checks)
        return await self._restored(rec, plan, target, why, applied_at, snapshot)

    def _elapsed(self, since: datetime) -> float:
        return (self._clock() - since).total_seconds()

    async def _connect(self, rec: RouterRecord, host: str) -> Transport:
        await self._pool.drop(rec.id)  # no backoff between the attempts of a reconnect window
        return await self._pool.get(rec.model_copy(update={"host": host}), token=self._holds.get(rec.id))

    async def _reconnect(
        self, rec: RouterRecord, target: str, applied_at: datetime, settle_s: float
    ) -> tuple[Transport | None, str | None]:
        await self._pool.drop(rec.id)
        await self._sleep(settle_s)
        carried = False
        while self._elapsed(applied_at) < self._window_s:
            try:
                return await self._connect(rec, target), None
            except HostKeyUnknown as exc:
                if not carried and target != rec.host and await self._carry(rec, target, exc.actual):
                    carried = True
                    continue  # the same router at its new address: connect again with the key pinned
                return None, f"{target} answers with a different host key, so it is not {rec.name}"
            except HostKeyChanged:
                pinned = f"the one pinned for {rec.name}"
                return None, f"{target} answers with a host key that differs from {pinned}"
            except TransportError:
                await self._sleep(self._every_s)
        return None, None

    async def _carry(self, rec: RouterRecord, target: str, offered: HostKeyInfo) -> bool:
        """Pin the key at `target` only when it is the key pinned for the old address. A router has one key
        per type and offers whichever comes first, so ask `target` for the pinned type before comparing."""
        kind = self._host_keys.key_type(rec.host, rec.port)
        if kind is not None and offered.type != kind:
            try:
                offered = await self._fetch_key(target, rec.port, algs=[kind])
            except TransportError:
                return False
        return self._host_keys.carry(rec.host, target, rec.port, offered)

    async def _confirm(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        t: Transport,
        target: str,
        confirm: str,
        destroy: str | None,
        seen: Sequence[NetCheck],
    ) -> NetApplyResult:
        checks = [NetCheck("reconnected", True, f"{rec.name} answered at {target}")]
        done = await self._run(t, rec, plan, confirm, source="app", require_guard=False)
        if not done.ok:
            checks.append(NetCheck("confirmed", False, _reason(done)))
            gone = f"Not applied: the router no longer held the change to confirm ({_reason(done)})"
            return self._finish(rec, plan, False, checks, gone, rec.host)
        checks.append(NetCheck("confirmed", True, "the router keeps the change"))
        if destroy is not None:
            with contextlib.suppress(TransportError):  # an unreached destroy: the session times out by itself
                await self._run(t, rec, plan, destroy, source="app", require_guard=False)
        host = rec.host
        if target != rec.host:
            self._routers.upsert(rec.model_copy(update={"host": target}))
            host = target
        error: str | None = None
        state = self._guard.state()
        if state.live:
            run = state.reasons[0].text if state.reasons else "a harness run"
            error = f"Confirmed although Bench Guard went live ({run})"
        return self._finish(rec, plan, True, [*checks, *seen], error, host)

    async def _restored(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        target: str,
        why: str | None,
        applied_at: datetime,
        snapshot: Snapshot | None,
    ) -> NetApplyResult:
        reason = why or f"{rec.name} did not answer at {target} within {self._window_s:g} s"
        error = (
            f"Not applied: {reason}. The router restores its previous {_settings(plan)} "
            f"{self._rollback_s:g} s after the change."
        )
        restored = await self._restore_check(rec, plan, applied_at, snapshot)
        return self._finish(
            rec, plan, False, [NetCheck("reconnected", False, reason), restored], error, rec.host
        )

    async def _unproven(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        target: str,
        seen: Sequence[NetCheck],
        applied_at: datetime,
        snapshot: Snapshot | None,
    ) -> NetApplyResult:
        """Reached, but the change is not in effect: no confirm, so rpcd's rollback undoes it."""
        failed = "; ".join(f"{c.name}: {c.detail}" for c in seen if c.ok is False)
        error = (
            f"Not applied: the change was not seen in effect ({failed}). The router restores its previous "
            f"{_settings(plan)} {self._rollback_s:g} s after the change."
        )
        reached = NetCheck("reconnected", True, f"{rec.name} answered at {target}")
        restored = await self._restore_check(rec, plan, applied_at, snapshot)
        return self._finish(rec, plan, False, [reached, *seen, restored], error, rec.host)

    async def _restore_check(
        self, rec: RouterRecord, plan: NetPlan, applied_at: datetime, snapshot: Snapshot | None
    ) -> NetCheck:
        """`restored`: after the rollback the router answers at its old address with its old settings. It may
        still be coming back at 65 s, so connecting is tried again for a while; a read that fails is "could
        not read", never "differs"."""
        await self._sleep(max(0.0, self._restore_s - self._elapsed(applied_at)))
        started = self._clock()
        while True:
            try:
                t = await self._connect(rec, rec.host)
                break
            except TransportError as exc:
                if self._elapsed(started) >= RESTORE_RETRY_S:
                    gone = f"{rec.name} does not answer at {rec.host} either: {exc}"
                    return NetCheck("restored", False, gone)
                await self._sleep(self._every_s)
        if snapshot is None:
            return NetCheck("restored", None, f"{rec.name} answers again at {rec.host}")
        try:
            shown = await self._run(t, rec, plan, snapshot.command, source="app", require_guard=False)
        except TransportError as exc:
            return NetCheck("restored", None, f"could not read the settings back: {exc}")
        if not shown.ok:
            return NetCheck("restored", None, f"could not read the settings back: {_reason(shown)}")
        if snapshot.parse(shown.stdout) == dict(snapshot.before):
            return NetCheck("restored", True, "the router is back on its previous settings")
        return NetCheck("restored", False, "the settings differ from before the change")
