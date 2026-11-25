"""The LTE screen's SIM, SMS and USSD cards (v1.3b E1): their reads and writes, beside LteService, whose
connection, modem device, AT lock and write slot they borrow."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from openwrtgui.guard.audit import HIDDEN, AuditLog, mask
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.lte import commands as c
from openwrtgui.lte.commands import Storage
from openwrtgui.lte.parse import parse_at
from openwrtgui.lte.service import PUT_BACK_SCREEN, SCREEN, LteService
from openwrtgui.lte.sim import NOTE_BLOCKED, NOTE_LAST_TRY, SimState, parse_sim_state
from openwrtgui.lte.sms import SmsMessage, check_text, parse_cpms, parse_ids, parse_message
from openwrtgui.lte.ussd import UssdReply, parse_cusd, reply_of
from openwrtgui.net.apply import NetPlan
from openwrtgui.store.routers import RouterRecord
from openwrtgui.transport.base import Transport, TransportError
from openwrtgui.wifi.service import PreviewChanged

NO_SIM_STATE = "The modem did not give its SIM state"
NO_PIN_ASKED = "The SIM does not ask for a PIN"
PIN_ACCEPTED = "PIN accepted"
PIN_NOT_TAKEN = "The SIM did not take the PIN"
VERIFY_TIMEOUT_S = 15.0
NO_MESSAGE_LIST = "The modem did not list its messages"
LIST_CHANGED = "The message list changed; preview again"
SEND_WARNING = "This sends an SMS from the router's SIM to {target}; the carrier may charge for it"
WRITE_TIMEOUT_S = 15.0
SEND_TIMEOUT_S = 15.0
USSD_WARNING = "The app listens up to 35 s for the network's reply; the AT console waits until then"
NO_AT_PORT = "No AT port answered on {name}"


class NoSuchMessage(LookupError):
    """An id that is not in the storage's list (404). Its text is "No message {id} in {storage}"."""


class ListChanged(PreviewChanged):
    """A message listed at the preview is gone at Apply (409): nothing is deleted."""

    def __init__(self, text: str) -> None:
        Exception.__init__(self, text)


@dataclass(frozen=True)
class SmsList:
    storage: Storage
    ids: tuple[int, ...]
    used: int | None
    capacity: int | None
    full: bool


@dataclass(frozen=True)
class SmsDone:
    ok: bool
    lines: tuple[str, ...]
    error: str | None


def _check_present(message_id: int, storage: Storage, listed: Sequence[int]) -> None:
    if message_id not in listed:
        raise NoSuchMessage(f"No message {message_id} in {storage}")


def _plan(rec: RouterRecord, lines: tuple[str, ...], warnings: tuple[str, ...]) -> NetPlan:
    """The preview of an SMS write: the commands as they will be sent (the digest names them)."""
    return NetPlan(
        router_id=rec.id,
        screen=SCREEN,
        config=None,
        lines=lines,
        ops=(),
        commands=lines,
        reloads=(),
        rollback=False,
        target_host=None,
        warnings=warnings,
        secrets=(),
    )


def _ussd_reply(stdout: str, request: str) -> tuple[UssdReply, bool]:
    """The reply, and whether the app closes the session (E9): the network asked for more, or no +CUSD came.

    The network's +CUSD answer comes after the request's OK (E8), past where parse_at's lines end, so every
    line microcom printed is searched. Its exit status is not: a reply that kept microcom listening past the
    35 s kill was still printed (P9). No +CUSD and an ERROR for the request: the modem refused it at once, an
    "error" with its line, not "no reply" (P10)."""
    parsed = parse_cusd([line.strip() for line in stdout.splitlines()])
    reply = reply_of(parsed)
    answer = parse_at(stdout, request) if parsed is None else None
    if answer is not None and answer.status == "ERROR":
        reply = UssdReply(status="error", text=answer.error, dcs=None, closed=False)
    return reply, parsed is None or reply.status == "more"


class PinRefused(Exception):
    """Enter PIN refused before anything is sent (409). Its text is one of this module's constants, never the
    PIN or the modem's answer."""


@dataclass(frozen=True)
class PinResult:
    accepted: bool
    sim: SimState
    message: str


def _refusal(state: SimState) -> str | None:
    """Why the PIN is not sent: the SIM does not ask for one, is blocked, or has one try left (E3)."""
    if state.pin == "blocked":
        return NOTE_BLOCKED
    if state.pin != "needed":
        return NO_PIN_ASKED
    if not state.can_enter_pin:
        return NOTE_LAST_TRY
    return None


def _not_taken(state: SimState) -> str:
    if state.tries_left is None:
        return PIN_NOT_TAKEN
    tries = "1 try" if state.tries_left == 1 else f"{state.tries_left} tries"
    return f"{PIN_NOT_TAKEN}: {tries} left"


def _result(after: SimState) -> PinResult:
    """Accepted: the SIM no longer asks for the PIN. A SIM blocked meanwhile (its tries spent elsewhere) is
    not called accepted."""
    if after.pin == "blocked":
        return PinResult(accepted=False, sim=after, message=NOTE_BLOCKED)
    if after.pin == "needed":
        return PinResult(accepted=False, sim=after, message=_not_taken(after))
    return PinResult(accepted=True, sim=after, message=PIN_ACCEPTED)


class ModemService:
    def __init__(self, *, lte: LteService, guard: BenchGuard, audit: AuditLog) -> None:
        self._lte = lte
        self._guard = guard
        self._audit = audit

    # ---------------------------------------------------------------- SIM (E2, E3, E4)
    async def _sim(self, t: Transport, device: str) -> SimState:
        """--uim-get-sim-state, then --get-pin-status when that fails or does not parse (E2). A read: not
        audited, allowed during a harness run."""
        for read in (c.SIM_STATE, c.PIN_STATUS):
            result = await t.run(read(device))
            state = parse_sim_state(result.stdout) if result.ok else None
            if state is not None:
                return state
        raise ValueError(NO_SIM_STATE)

    async def sim(self, router_id: str) -> SimState:
        _rec, t, device = await self._lte.connection(router_id)
        return await self._sim(t, device)

    async def enter_pin(self, router_id: str, pin: str) -> PinResult:
        """E4: the PIN rule before anything is sent, Bench Guard clear, the write slot, audited with the PIN
        hidden. The SIM's state is read inside the slot, right before the PIN goes, so two tries can never
        both pass the last-try check (E3)."""
        rec, t, device = await self._lte.connection(router_id)
        command = c.verify_pin1(device, pin)
        self._guard.require_clear()
        async with self._lte.write_slot(rec):
            refusal = _refusal(await self._sim(t, device))
            if refusal is not None:
                raise PinRefused(refusal)
            try:
                await run_audited(
                    t,
                    command,
                    router_id=rec.id,
                    screen=SCREEN,
                    guard=self._guard,
                    audit=self._audit,
                    secrets=(pin,),
                    timeout=VERIFY_TIMEOUT_S,
                )
            except TransportError as exc:  # an error that names the command would show the PIN (E4)
                if pin in str(exc):
                    raise TransportError(str(exc).replace(pin, HIDDEN)) from None
                raise
            return _result(await self._sim(t, device))

    # ---------------------------------------------------------------- SMS (E5, E6, E7)
    async def _ids(self, t: Transport, device: str, storage: Storage) -> tuple[int, ...]:
        """The ids the modem lists in one storage: a read, not audited, allowed during a harness run."""
        result = await t.run(c.list_messages(device, storage))
        ids = parse_ids(result.stdout) if result.ok else None
        if ids is None:
            raise ValueError(NO_MESSAGE_LIST)
        return ids

    async def _use(self, rec: RouterRecord, t: Transport, storage: Storage) -> tuple[int, int] | None:
        """AT+CPMS? is the only read of a storage's use: an app-internal AT query, not audited (P3). None when
        no AT port answers."""
        async with self._lte.at_lock(rec.id):
            port = await self._lte.at_port(rec, t)
            if port is None:
                return None
            command = "AT+CPMS?"
            result = await t.run(c.at(port, command))
            answer = parse_at(result.stdout, command) if result.ok else None
            return parse_cpms(answer.lines).get(storage) if answer is not None else None

    async def messages(self, router_id: str, storage: Storage) -> SmsList:
        rec, t, device = await self._lte.connection(router_id)
        ids = await self._ids(t, device, storage)
        use = await self._use(rec, t, storage)
        used, capacity = use if use is not None else (None, None)
        return SmsList(
            storage=storage,
            ids=ids,
            used=used,
            capacity=capacity,
            full=capacity is not None and used is not None and used >= capacity,
        )

    async def message(self, router_id: str, storage: Storage, message_id: int) -> SmsMessage:
        """E5: read during a run too; the audit holds the command, never the text."""
        rec, t, device = await self._lte.connection(router_id)
        _check_present(message_id, storage, await self._ids(t, device, storage))
        result = await run_audited(
            t,
            c.get_message(device, storage, message_id),
            router_id=rec.id,
            screen=SCREEN,
            guard=self._guard,
            audit=self._audit,
            require_guard=False,
        )
        message = parse_message(result.stdout, message_id, storage) if result.ok else None
        if message is None:
            raise ValueError(f"The modem did not give message {message_id} of {storage}")
        return message

    def _delete_plan(self, rec: RouterRecord, device: str, storage: Storage, ids: Sequence[int]) -> NetPlan:
        return _plan(rec, tuple(c.delete_message(device, storage, i) for i in dict.fromkeys(ids)), ())

    async def plan_delete(self, router_id: str, storage: Storage, ids: Sequence[int]) -> NetPlan:
        rec, t, device = await self._lte.connection(router_id)
        listed = await self._ids(t, device, storage)
        for message_id in ids:
            _check_present(message_id, storage, listed)
        return self._delete_plan(rec, device, storage, ids)

    async def delete(self, router_id: str, storage: Storage, ids: Sequence[int], digest: str) -> SmsDone:
        """E7: the list is read again inside the slot; an id gone since the preview is a 409, nothing sent."""
        rec, t, device = await self._lte.connection(router_id)
        self._guard.require_clear()
        async with self._lte.write_slot(rec):
            listed = await self._ids(t, device, storage)
            if any(i not in listed for i in ids):
                raise ListChanged(LIST_CHANGED)
            plan = self._delete_plan(rec, device, storage, ids)
            if plan.digest != digest:
                raise PreviewChanged(rec.name)
            return await self._run_all(rec, t, plan, secrets=())

    def _send_plan(self, rec: RouterRecord, device: str, target: str, text: str) -> NetPlan:
        command = c.send_message(device, target, check_text(text))
        return _plan(rec, (command,), (SEND_WARNING.format(target=target),))

    async def plan_send(self, router_id: str, target: str, text: str) -> NetPlan:
        """E6: the preview shows the person's own text; the audit will not."""
        rec, _t, device = await self._lte.connection(router_id)
        return self._send_plan(rec, device, target, text)

    async def send(self, router_id: str, target: str, text: str, digest: str) -> SmsDone:
        rec, t, device = await self._lte.connection(router_id)
        plan = self._send_plan(rec, device, target, text)
        self._guard.require_clear()
        async with self._lte.write_slot(rec):
            if plan.digest != digest:
                raise PreviewChanged(rec.name)
            return await self._run_all(rec, t, plan, secrets=(text,), timeout=SEND_TIMEOUT_S)

    async def _run_all(
        self,
        rec: RouterRecord,
        t: Transport,
        plan: NetPlan,
        *,
        secrets: tuple[str, ...],
        timeout: float = WRITE_TIMEOUT_S,
    ) -> SmsDone:
        """One audited command per plan line, in order; the first failure stops the rest."""
        done: list[str] = []
        for line in plan.lines:
            result = await run_audited(
                t,
                line,
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                secrets=secrets,
                timeout=timeout,
            )
            if not result.ok:
                reason = (result.stderr or result.stdout).strip() or f"exit {result.exit_status}"
                return SmsDone(ok=False, lines=tuple(done), error=mask(reason, secrets))
            done.append(line)
        return SmsDone(ok=True, lines=tuple(done), error=None)

    # ---------------------------------------------------------------- USSD (E8, E9)
    async def _at_port(self, rec: RouterRecord, t: Transport) -> str:
        """The modem's AT port; the caller holds the AT lock."""
        port = await self._lte.at_port(rec, t)
        if port is None:
            raise ValueError(NO_AT_PORT.format(name=rec.name))
        return port

    def _ussd_plan(self, rec: RouterRecord, port: str, code: str) -> NetPlan:
        return _plan(rec, (c.ussd(port, code),), (USSD_WARNING,))

    async def plan_ussd(self, router_id: str, code: str) -> NetPlan:
        """The line names the AT port: finding it takes the AT lock, so a preview waits behind a running
        exchange as the AT console does."""
        rec, t, _device = await self._lte.connection(router_id)
        async with self._lte.at_lock(rec.id):
            port = await self._at_port(rec, t)
        return self._ussd_plan(rec, port, code)

    async def ussd(self, router_id: str, code: str, digest: str) -> UssdReply:
        """E8: the request and its 35 s listen hold the write slot, and with it the AT lock. The port is found
        inside the slot, so a USSD refuses (409) behind another write instead of waiting for the AT lock.
        A harness run that starts during the wait ends nothing: the request went out before, and its reply
        comes back (Review Focus 4)."""
        rec, t, _device = await self._lte.connection(router_id)
        self._guard.require_clear()
        async with self._lte.write_slot(rec):
            port = await self._at_port(rec, t)
            plan = self._ussd_plan(rec, port, code)
            if plan.digest != digest:
                raise PreviewChanged(rec.name)
            done = await run_audited(
                t,
                plan.lines[0],
                router_id=rec.id,
                screen=SCREEN,
                guard=self._guard,
                audit=self._audit,
                timeout=c.USSD_TIMEOUT_S,
            )
            reply, close = _ussd_reply(done.stdout, c.ussd_request(code))
            if not close:
                return reply
            return replace(reply, closed=await self._cancel(rec, t, port))

    async def _cancel(self, rec: RouterRecord, t: Transport, port: str) -> bool:
        """E9: AT+CUSD=2 through the 2 s AT path, for a menu the app cannot follow or a reply that never came.
        It ends only the session this request opened, so a harness run that started during the wait does not
        stop it: it is then sent past Bench Guard and audited as a put-back line (spec 4.2). True: the modem
        took it."""
        screen = PUT_BACK_SCREEN if self._guard.state().live else SCREEN
        try:
            done = await run_audited(
                t,
                c.at(port, c.USSD_CANCEL),
                router_id=rec.id,
                screen=screen,
                guard=self._guard,
                audit=self._audit,
                require_guard=False,
            )
        except TransportError:  # the reply is already in hand: it still goes back, not closed
            return False
        answer = parse_at(done.stdout, c.USSD_CANCEL)
        return answer is not None and answer.status == "OK"
