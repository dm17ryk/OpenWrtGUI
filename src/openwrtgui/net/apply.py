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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openwrtgui.guard.audit import AuditLog, Source, mask
from openwrtgui.guard.bench_guard import BenchGuard, GuardLocked
from openwrtgui.guard.writes import run_audited
from openwrtgui.luci_bridge.session import create_command, destroy_command
from openwrtgui.net.commands import UCI_NETWORK
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import (
    CommandResult,
    HostKeyUnknown,
    Transport,
    TransportError,
    ubus_call,
    ubus_command,
)
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.transport.ssh import HostKeyStore
from openwrtgui.uci import UciOp, drop_unchanged, order_for_script, parse_uci_show, render_uci

ROLLBACK_S = 60
RECONNECT_WINDOW_S = 40.0
RECONNECT_EVERY_S = 2.0
SETTLE_S = 2.0
RESTORE_CHECK_S = 65.0
SCRIPT_TIMEOUT_S = 60.0
SESSION = "<session>"
NOTHING = "Nothing to apply: the router already has these settings."


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


def rollback_warning(router_name: str, target: str) -> str:
    return (
        f"Applies with a {ROLLBACK_S} s rollback: if the app cannot reach {router_name} at {target} again "
        "and confirm, the router restores its previous network settings by itself."
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
) -> NetPlan:
    """The exact preview: only changes, section deletes last; nothing left is refused with NOTHING."""
    kept = order_for_script(drop_unchanged(ops, current), current)
    if not kept and not commands:
        raise ValueError(NOTHING)
    if rollback:
        if config is None:
            raise ValueError("a rollback change names its config")
        create, grant, apply, confirm, destroy = session_commands(SESSION, config)
        script = _script(kept, config, SESSION).splitlines()
        lines = [create, grant, *script, apply, *commands, confirm, destroy]
    else:
        lines = [*(_script(kept, config, None).splitlines() if kept else []), *commands, *reloads]
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
    )


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _holds(op: UciOp, shown: Mapping[str, str]) -> bool:
    if op.op == "add":
        return True
    if "$" in op.path:  # an option of a section the script made: some section of the config has it
        config, option = op.path.split(".", 1)[0], op.path.rsplit(".", 1)[-1]
        return op.op == "delete" or any(
            k.startswith(config + ".") and k.endswith("." + option) and v == op.value
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


async def saved_check(t: Transport, show_command: str, ops: Sequence[UciOp]) -> NetCheck:
    """`saved`: the config read back holds every change of the plan."""
    shown = parse_uci_show((await t.run(show_command)).stdout)
    wrong = [op.path for op in ops if not _holds(op, shown)]
    if wrong:
        return NetCheck("saved", False, "not as asked: " + ", ".join(wrong))
    return NetCheck("saved", True, "the router has the change")


async def service_check(t: Transport, name: str) -> NetCheck:
    """`<service>`: procd has a running instance of it."""
    listed = await ubus_call(t, "service", "list", {"name": name}) or {}
    instances = listed.get(name, {}).get("instances", {})
    running = any(isinstance(i, dict) and i.get("running") for i in instances.values())
    return NetCheck(name, running, "running" if running else f"{name} is not running")


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

    async def run(
        self,
        rec: RouterRecord,
        t: Transport,
        plan: NetPlan,
        verify: Verifier,
        snapshot: Mapping[str, str] | None = None,
    ) -> NetApplyResult:
        self._guard.require_clear()
        async with self._pool.write_lock(rec.id):
            if plan.rollback:
                return await self._with_rollback(rec, t, plan, verify, snapshot)
            return await self._plain(rec, t, plan, verify)

    # ------------------------------------------------------------------ plain
    async def _plain(
        self, rec: RouterRecord, t: Transport, plan: NetPlan, verify: Verifier
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
                done = await self._run(t, rec, plan, command, secrets=plan.secrets)
                if not done.ok:
                    return self._finish(
                        rec, plan, applied, (), f"{command} failed: {_reason(done)}", rec.host
                    )
                applied = True
            error: str | None = None
            for reload in plan.reloads:
                done = await self._run(t, rec, plan, reload, timeout=SCRIPT_TIMEOUT_S)
                if not done.ok:
                    error = f"The reload failed after the change was saved: {_reason(done)}"
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
        snapshot: Mapping[str, str] | None,
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
        applied_at = self._clock()
        target = plan.target_host or rec.host
        t2, why = await self._reconnect(rec, target, applied_at)
        if t2 is None:
            return await self._restored(rec, plan, target, why, applied_at, snapshot)
        return await self._confirm(rec, plan, t2, target, confirm, destroy, verify)

    def _elapsed(self, since: datetime) -> float:
        return (self._clock() - since).total_seconds()

    async def _connect(self, rec: RouterRecord, host: str) -> Transport:
        await self._pool.drop(rec.id)  # no backoff between the attempts of a reconnect window
        return await self._pool.get(rec.model_copy(update={"host": host}))

    async def _reconnect(
        self, rec: RouterRecord, target: str, applied_at: datetime
    ) -> tuple[Transport | None, str | None]:
        await self._pool.drop(rec.id)
        await self._sleep(SETTLE_S)
        carried = False
        while self._elapsed(applied_at) < self._window_s:
            try:
                return await self._connect(rec, target), None
            except HostKeyUnknown as exc:
                if (
                    not carried
                    and target != rec.host
                    and self._host_keys.carry(rec.host, target, rec.port, exc.actual)
                ):
                    carried = True
                    continue  # the same router at its new address: connect again with the key pinned
                return None, f"{target} answers with a different host key, so it is not {rec.name}"
            except TransportError:
                await self._sleep(self._every_s)
        return None, None

    async def _confirm(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        t: Transport,
        target: str,
        confirm: str,
        destroy: str,
        verify: Verifier,
    ) -> NetApplyResult:
        checks = [NetCheck("reconnected", True, f"{rec.name} answered at {target}")]
        done = await self._run(t, rec, plan, confirm, source="app", require_guard=False)
        if not done.ok:
            checks.append(NetCheck("confirmed", False, _reason(done)))
            gone = f"Not applied: the router no longer held the change to confirm ({_reason(done)})"
            return self._finish(rec, plan, False, checks, gone, rec.host)
        checks.append(NetCheck("confirmed", True, "the router keeps the change"))
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
        try:
            checks += await verify(t)
        except TransportError as exc:
            checks.append(NetCheck("verify", None, f"not run: {exc}"))
        return self._finish(rec, plan, True, checks, error, host)

    async def _restored(
        self,
        rec: RouterRecord,
        plan: NetPlan,
        target: str,
        why: str | None,
        applied_at: datetime,
        snapshot: Mapping[str, str] | None,
    ) -> NetApplyResult:
        reason = why or f"{rec.name} did not answer at {target} within {self._window_s:g} s"
        error = (
            f"Not applied: {reason}. The router restores its previous network settings "
            f"{self._rollback_s:g} s after the change."
        )
        checks = [NetCheck("reconnected", False, reason)]
        await self._sleep(max(0.0, self._restore_s - self._elapsed(applied_at)))
        try:
            t = await self._connect(rec, rec.host)
            shown = await self._run(t, rec, plan, UCI_NETWORK, source="app", require_guard=False)
            now = {k: v for k, v in parse_uci_show(shown.stdout).items() if k.startswith("network.")}
            if snapshot is None:
                checks.append(NetCheck("restored", None, f"{rec.name} answers again at {rec.host}"))
            elif now == dict(snapshot):
                checks.append(
                    NetCheck("restored", True, "the router is back on its previous network settings")
                )
            else:
                checks.append(
                    NetCheck("restored", False, "the network settings differ from before the change")
                )
        except TransportError as exc:
            checks.append(
                NetCheck("restored", False, f"{rec.name} does not answer at {rec.host} either: {exc}")
            )
        return self._finish(rec, plan, False, checks, error, rec.host)
