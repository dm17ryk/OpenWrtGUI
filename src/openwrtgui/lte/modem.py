"""The LTE screen's SIM, SMS and USSD cards (v1.3b E1): their reads and writes, beside LteService, whose
connection, modem device, AT lock and write slot they borrow."""

from __future__ import annotations

from dataclasses import dataclass

from openwrtgui.guard.audit import HIDDEN, AuditLog
from openwrtgui.guard.bench_guard import BenchGuard
from openwrtgui.guard.writes import run_audited
from openwrtgui.lte import commands as c
from openwrtgui.lte.service import SCREEN, LteService
from openwrtgui.lte.sim import NOTE_BLOCKED, NOTE_LAST_TRY, SimState, parse_sim_state
from openwrtgui.transport.base import Transport, TransportError

NO_SIM_STATE = "The modem did not give its SIM state"
NO_PIN_ASKED = "The SIM does not ask for a PIN"
PIN_ACCEPTED = "PIN accepted"
PIN_NOT_TAKEN = "The SIM did not take the PIN"
VERIFY_TIMEOUT_S = 15.0


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
