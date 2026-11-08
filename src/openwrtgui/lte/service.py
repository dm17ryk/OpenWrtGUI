"""The LTE screen's service: the state, connect / disconnect / reboot modem, the AT console and settings."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from openwrtgui.forms import OptionRow
from openwrtgui.guard.audit import AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.lte import commands as c
from openwrtgui.lte.at import AtResult, find_at_port, is_query
from openwrtgui.lte.commands import MODEM_DEVICE
from openwrtgui.lte.parse import parse_at, parse_opmode
from openwrtgui.lte.settings import LteSettings, settings_request
from openwrtgui.lte.state import NO_LTE, LteState, read_lte
from openwrtgui.net.apply import NetApplyResult, NetCheck, NetPlan, net_plan
from openwrtgui.net.interfaces import InterfaceRequest, dynamic_refusal
from openwrtgui.net.service import NetworkService
from openwrtgui.net.state import NetworkState
from openwrtgui.store.routers import RouterRecord, RouterStore
from openwrtgui.transport.base import CommandResult, Transport
from openwrtgui.transport.pool import ConnectionPool
from openwrtgui.wifi.service import PreviewChanged

SCREEN = "LTE"
LteAction = Literal["connect", "disconnect", "reboot"]
CONNECT_S = 60.0
DISCONNECT_S = 20.0
POLL_S = 2.0  # the nominal step: CONNECT_S / POLL_S polls, whatever poll_s is set to
READBACK_TRIES = 3
NO_ADDRESS = "no address yet: waiting for the carrier's DHCP"
DROPS = "{name}'s LTE session drops; devices that route through it lose the internet until it is back"


NEEDS_CONFIRM = "This command may change the modem; send it again with confirm"
NO_MODEM_ANSWER = "No answer from the modem"
IMEI_RULE = re.compile(r"[0-9]{15}")


class LteBusy(Exception):
    """One LTE action at a time per router (409)."""


class AtNeedsConfirm(Exception):
    """D5: an AT command that is not a query runs only once the person confirms it (428)."""


def _reason(result: CommandResult) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"


def _qmi_of(state: NetworkState) -> tuple[str, str | None] | None:
    """The qmi interface's name and device; None: no LTE modem interface on this router."""
    conf = next((v.conf for v in state.interfaces if v.conf is not None and v.conf.proto == "qmi"), None)
    return (conf.name, conf.device) if conf is not None else None


def _lte_name(qmi: tuple[str, str | None] | None) -> str:
    """The actions send `ifup lte` / `ifdown lte`: the qmi interface has to be the one called lte."""
    if qmi is None:
        raise ValueError(NO_LTE)
    if qmi[0] != "lte":
        raise ValueError(f"The LTE screen expects the qmi interface to be called lte; it is {qmi[0]}")
    return qmi[0]


class LteService:
    def __init__(
        self,
        *,
        pool: ConnectionPool,
        routers: RouterStore,
        guard: BenchGuard,
        audit: AuditLog,
        net: NetworkService,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = pool
        self._routers = routers
        self._guard = guard
        self._audit = audit
        self._net = net
        self._clock = clock
        self._sleep = sleep
        self._ports: dict[str, tuple[int, str | None]] = {}  # router → (connection, AT port found on it)
        self._busy: dict[str, asyncio.Lock] = {}
        self.poll_s = POLL_S
        self.readback_s = 1.0

    def _record(self, router_id: str) -> RouterRecord:
        rec = self._routers.get(router_id)
        if rec is None:
            raise ValueError(f"Unknown router {router_id}")
        return rec

    async def _qmi(self, router_id: str) -> tuple[str, str | None] | None:
        return _qmi_of(await self._net.state(router_id))

    async def modem_device(self, router_id: str) -> str | None:
        """The qmi interface's device when it is a QMI modem device (`/dev/cdc-wdmN`); None: no LTE here."""
        qmi = await self._qmi(router_id)
        device = qmi[1] if qmi is not None else None
        return device if device is not None and MODEM_DEVICE.fullmatch(device) else None

    async def at_port(self, rec: RouterRecord, t: Transport) -> str | None:
        """D4: found once per connection (a reconnect may follow a modem that re-enumerated)."""
        cached = self._ports.get(rec.id)
        if cached is not None and cached[0] == id(t):
            return cached[1]
        port = await find_at_port(t)
        self._ports[rec.id] = (id(t), port)
        return port

    async def state(self, router_id: str) -> LteState:
        rec = self._record(router_id)
        qmi = await self._qmi(router_id)
        t = await self._pool.get(rec)
        port = await self.at_port(rec, t) if qmi is not None else None
        return await read_lte(t, router_id=rec.id, qmi=qmi, at_port=port, now=self._clock())

    # ---------------------------------------------------------------- connect, disconnect, reboot modem
    async def _lte_device(self, router_id: str) -> str | None:
        qmi = await self._qmi(router_id)
        _lte_name(qmi)
        device = qmi[1] if qmi is not None else None
        return device if device is not None and MODEM_DEVICE.fullmatch(device) else None

    async def plan_action(self, router_id: str, action: LteAction) -> NetPlan:
        rec = self._record(router_id)
        device = await self._lte_device(router_id)
        drops = DROPS.format(name=rec.name)
        if action == "connect":
            lines, warnings = [c.IFUP_LTE], []
        elif action == "disconnect":
            lines, warnings = [c.IFDOWN_LTE], [drops]
        else:
            if device is None:
                raise ValueError("Reboot needs the modem's QMI device (/dev/cdc-wdmN) in network.lte.device")
            lines = [
                c.set_opmode(device, "low_power"),
                c.OPMODE(device),
                c.set_opmode(device, "online"),
                c.OPMODE(device),
                c.IFUP_LTE,
            ]
            warnings = [drops]
        return net_plan(
            router_id=rec.id,
            screen=SCREEN,
            config=None,
            ops=[],
            current={},
            commands=lines,
            warnings=warnings,
        )

    async def apply_action(self, router_id: str, action: LteAction, digest: str) -> NetApplyResult:
        rec = self._record(router_id)
        busy = self._busy.setdefault(rec.id, asyncio.Lock())
        if busy.locked():
            raise LteBusy(f"An LTE action is already running on {rec.name}")
        async with busy:
            self._guard.require_clear()
            plan = await self.plan_action(router_id, action)
            if plan.digest != digest:
                raise PreviewChanged(rec.name)
            t = await self._pool.get(rec)
            async with self._pool.write_lock(rec.id):
                return await self._run_action(rec, t, action, plan.lines)

    async def _cmd(self, rec: RouterRecord, t: Transport, command: str) -> CommandResult:
        return await run_audited(
            t, command, router_id=rec.id, screen=SCREEN, guard=self._guard, audit=self._audit
        )

    async def _run_action(
        self, rec: RouterRecord, t: Transport, action: LteAction, lines: tuple[str, ...]
    ) -> NetApplyResult:
        checks: list[NetCheck] = []
        if action == "reboot":
            for set_line, read_line, mode in (
                (lines[0], lines[1], "low_power"),
                (lines[2], lines[3], "online"),
            ):
                done = await self._cmd(rec, t, set_line)
                if not done.ok:
                    return NetApplyResult(
                        rec.id, False, False, tuple(checks), f"{set_line}: {_reason(done)}", rec.host
                    )
                ok = await self._readback(rec, t, read_line, mode)
                checks.append(NetCheck(f"modem {mode}", ok, mode if ok else f"still not {mode}"))
                if not ok:
                    error = f"The modem did not go {mode}; it may need ifup lte or a power cycle"
                    return NetApplyResult(rec.id, True, False, tuple(checks), error, rec.host)
        command = c.IFDOWN_LTE if action == "disconnect" else c.IFUP_LTE
        done = await self._cmd(rec, t, command)
        if not done.ok:
            return NetApplyResult(
                rec.id, False, False, tuple(checks), f"{command}: {_reason(done)}", rec.host
            )
        if action == "disconnect":
            down = await self._wait_up(t, want=False, limit_s=DISCONNECT_S)
            checks.append(
                NetCheck("lte down", down, "down" if down else f"still up after {DISCONNECT_S:g} s")
            )
        else:
            up = await self._wait_up(t, want=True, limit_s=CONNECT_S)
            checks.append(NetCheck("lte up", up, "up" if up else f"not up after {CONNECT_S:g} s"))
            if up:
                address = await self._address(t)
                checks.append(NetCheck("lte_4 address", True if address else None, address or NO_ADDRESS))
        verified = all(check.ok is not False for check in checks)
        return NetApplyResult(rec.id, True, verified, tuple(checks), None, rec.host)

    async def _readback(self, rec: RouterRecord, t: Transport, read_line: str, mode: str) -> bool:
        for attempt in range(READBACK_TRIES):
            if attempt:
                await self._sleep(self.readback_s)
            answer = await self._cmd(rec, t, read_line)
            if answer.ok and parse_opmode(answer.stdout) == mode:
                return True
        return False

    async def _status(self, t: Transport, name: str) -> dict[str, object] | None:
        result = await t.run(c.iface_status(name))
        try:
            data = json.loads(result.stdout) if result.ok else None
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def _wait_up(self, t: Transport, *, want: bool, limit_s: float) -> bool:
        for attempt in range(max(1, int(limit_s / POLL_S))):
            if attempt:
                await self._sleep(self.poll_s)
            status = await self._status(t, "lte")
            if status is not None and bool(status.get("up")) is want:
                return True
        return False

    # ---------------------------------------------------------------- settings (v0.3's interface plan)
    async def _settings_request(self, router_id: str, settings: LteSettings) -> InterfaceRequest:
        state = await self._net.state(router_id)
        name = _lte_name(_qmi_of(state))
        for edit in settings.edits:
            if edit.section != name:
                raise ValueError(
                    dynamic_refusal(state, edit.section)
                    or f"The LTE settings change {name} only, not {edit.section}"
                )
        return settings_request(name, settings)

    async def plan_settings(self, router_id: str, settings: LteSettings) -> NetPlan:
        return await self._net.plan_interface(router_id, await self._settings_request(router_id, settings))

    async def apply_settings(self, router_id: str, settings: LteSettings, digest: str) -> NetApplyResult:
        req = await self._settings_request(router_id, settings)
        return await self._net.apply_interface(router_id, req, digest)

    async def settings_options(self, router_id: str) -> list[OptionRow]:
        name = _lte_name(await self._qmi(router_id))
        return await self._net.interface_options(router_id, name)

    # ---------------------------------------------------------------- AT console and IMEI
    async def at_command(self, router_id: str, text: str, confirmed: bool) -> AtResult:
        """D5: no preview, every line audited. Queries run any time; anything else needs Bench Guard clear,
        the person's confirmation and the write lock."""
        rec = self._record(router_id)
        command = c.check_at(text)
        query = is_query(command)
        if not query:
            self._guard.require_clear()
            if not confirmed:
                raise AtNeedsConfirm(NEEDS_CONFIRM)
        t = await self._pool.get(rec)
        port = await self.at_port(rec, t)
        if port is None:
            return AtResult(
                command=command, lines=(), status="no answer", error=f"No AT port answered on {rec.name}"
            )
        line = c.at(port, command)
        if query:
            done = await run_audited(
                t,
                line,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                require_guard=False,
            )
        else:
            async with self._pool.write_lock(rec.id):
                done = await self._cmd(rec, t, line)
        answer = parse_at(done.stdout, command)
        if answer is None:
            return AtResult(command=command, lines=(), status="no answer", error=NO_MODEM_ANSWER)
        return AtResult(command=command, lines=answer.lines, status=answer.status, error=answer.error)

    async def imei(self, router_id: str) -> str:
        """D3: read only when the person asks; never stored, logged or audited."""
        rec = self._record(router_id)
        device = await self.modem_device(router_id)
        if device is None:
            raise ValueError(NO_LTE)
        t = await self._pool.get(rec)
        result = await t.run(c.IMEI(device))
        try:
            value = json.loads(result.stdout) if result.ok else None
        except ValueError:
            value = None
        if not isinstance(value, str) or not IMEI_RULE.fullmatch(value):
            raise ValueError("The modem did not give its IMEI")
        return value

    async def _address(self, t: Transport) -> str | None:
        status = await self._status(t, "lte_4")
        addresses = status.get("ipv4-address") if status else None
        first = addresses[0] if isinstance(addresses, list) and addresses else None
        address = first.get("address") if isinstance(first, dict) else None
        return address if isinstance(address, str) else None
