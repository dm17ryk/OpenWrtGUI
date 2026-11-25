"""The SIM card's endpoints (v1.3b E3, E4) in the simulator: the PIN state, and Enter PIN, never on the last
try, the PIN shown nowhere but the one command sent."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from openwrtgui.context import AppContext
from openwrtgui.lte.sim import NOTE_BLOCKED, NOTE_LAST_TRY
from openwrtgui.simmodem import SimModem
from openwrtgui.transport.base import CommandResult, TransportError
from openwrtgui.transport.fake import ReplayTransport

SIM = "/api/routers/ap1/lte/sim"
PIN = f"{SIM}/pin"
VERIFY = "--verify-pin1"
AUDITED_VERIFY = "uqmi -s -d /dev/cdc-wdm0 -t 5000 --verify-pin1 <hidden>"
NOTE_NO_TRIES = (
    "The modem did not say how many tries are left: enter the PIN in a phone or the D-Link UI, "
    "so a wrong PIN does not block the SIM"
)
OFF = {
    "pin": "off",
    "tries_left": 3,
    "puk_tries_left": 10,
    "card": "ready",
    "can_enter_pin": False,
    "note": None,
}


async def _modem(ctx: AppContext) -> SimModem:
    t = await ctx.pool.get(ctx.routers.get("ap1"))  # type: ignore[arg-type]
    assert isinstance(t, ReplayTransport) and t.state is not None and t.state.modem is not None
    return t.state.modem


async def _sent(ctx: AppContext) -> list[str]:
    """Every command the simulated modem is asked from now on, audited or not."""
    modem = await _modem(ctx)
    real = modem.answer
    sent: list[str] = []

    def recording(command: str) -> CommandResult | None:
        sent.append(command)
        return real(command)

    modem.answer = recording  # type: ignore[method-assign]
    return sent


def _audited(ctx: AppContext) -> list[str]:
    return [e.command for e in reversed(ctx.audit.query())]


async def _needs_pin(ctx: AppContext, tries: int = 3) -> SimModem:
    modem = await _modem(ctx)
    modem.pin1, modem.pin1_tries = "not_verified", tries
    return modem


# ---------------------------------------------------------------- the SIM state
async def test_the_sim_state_of_a_sim_with_its_pin_off(authed: httpx.AsyncClient) -> None:
    answer = await authed.get(SIM)
    assert (answer.status_code, answer.json()) == (200, OFF)


async def test_the_sim_state_is_a_read_allowed_during_a_run(
    authed_guard_live: httpx.AsyncClient, ctx_guard_live: AppContext
) -> None:
    answer = await authed_guard_live.get(SIM)
    assert (answer.status_code, answer.json()) == (200, OFF)
    assert ctx_guard_live.audit.query() == []


async def test_the_pin_status_is_the_fallback(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _modem(ctx)
    real = modem.answer

    def no_sim_state(command: str) -> CommandResult | None:
        if "--uim-get-sim-state" in command:
            return CommandResult(command, "", "Not supported\n", 1)
        return real(command)

    modem.answer = no_sim_state  # type: ignore[method-assign]
    answer = await authed.get(SIM)
    assert (answer.status_code, answer.json()) == (200, {**OFF, "card": None})


async def test_no_sim_state_from_either_read_is_a_422(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _modem(ctx)
    real = modem.answer

    def unparsable(command: str) -> CommandResult | None:
        if "--uim-get-sim-state" in command or "--get-pin-status" in command:
            return CommandResult(command, "not json\n", "", 0)
        return real(command)

    modem.answer = unparsable  # type: ignore[method-assign]
    answer = await authed.get(SIM)
    assert (answer.status_code, answer.json()) == (422, {"detail": "The modem did not give its SIM state"})


# ---------------------------------------------------------------- Enter PIN
async def test_the_right_pin_is_accepted(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _needs_pin(ctx)
    answer = await authed.post(PIN, json={"pin": "0000"})
    assert answer.status_code == 200
    body = answer.json()
    assert (body["accepted"], body["sim"]["pin"], body["message"]) == (True, "entered", "PIN accepted")
    assert modem.pin1 == "verified"


async def test_a_wrong_pin_says_how_many_tries_are_left(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    modem = await _needs_pin(ctx)
    answer = await authed.post(PIN, json={"pin": "9999"})
    assert answer.status_code == 200
    body = answer.json()
    assert (body["accepted"], body["message"]) == (False, "The SIM did not take the PIN: 2 tries left")
    assert (body["sim"]["pin"], body["sim"]["tries_left"], body["sim"]["can_enter_pin"]) == (
        "needed",
        2,
        True,
    )
    assert modem.pin1_tries == 2


async def test_a_wrong_pin_that_leaves_one_try_says_one_try(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    await _needs_pin(ctx, tries=2)
    body = (await authed.post(PIN, json={"pin": "9999"})).json()
    assert (body["accepted"], body["message"]) == (False, "The SIM did not take the PIN: 1 try left")
    assert (body["sim"]["can_enter_pin"], body["sim"]["note"]) == (False, NOTE_LAST_TRY)


async def test_a_sim_blocked_by_the_try_is_not_called_accepted(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """The state after the try is no longer "needed", yet the PIN was not taken: something else spent the
    SIM's tries meanwhile (a phone, the D-Link UI)."""
    modem = await _needs_pin(ctx)
    real = modem.answer

    def blocked_meanwhile(command: str) -> CommandResult | None:
        if VERIFY in command:
            modem.pin1, modem.pin1_tries = "blocked", 0
            return CommandResult(command, "", "Request failed\n", 1)
        return real(command)

    modem.answer = blocked_meanwhile  # type: ignore[method-assign]
    body = (await authed.post(PIN, json={"pin": "9999"})).json()
    assert (body["accepted"], body["message"], body["sim"]["pin"]) == (False, NOTE_BLOCKED, "blocked")


SENT_NO_STATE = (
    "The PIN was sent, but the SIM's state could not be read: check the tries left before trying again"
)
SENT_STATE_UNKNOWN = "The PIN was sent; check the SIM's state before trying again"


@pytest.mark.parametrize(
    ("after", "accepted", "message"),
    [("disabled", True, "PIN accepted"), ("changed", False, SENT_STATE_UNKNOWN)],
)
async def test_only_entered_or_off_after_the_try_is_accepted(
    authed: httpx.AsyncClient, ctx: AppContext, after: str, accepted: bool, message: str
) -> None:
    """Final review I3 (b): a state the app does not know after the try is not "PIN accepted"."""
    modem = await _needs_pin(ctx)
    real = modem.answer

    def becomes(command: str) -> CommandResult | None:
        if VERIFY in command:
            modem.pin1 = after
            return CommandResult(command, "", "", 0)
        return real(command)

    modem.answer = becomes  # type: ignore[method-assign]
    answer = await authed.post(PIN, json={"pin": "0000"})
    assert answer.status_code == 200 and "0000" not in answer.text
    body = answer.json()
    assert (body["accepted"], body["message"]) == (accepted, message)
    assert body["sim"]["pin"] == ("off" if after == "disabled" else "unknown")


@pytest.mark.parametrize("fault", ["unreadable", "lost"])
async def test_a_failed_read_back_says_the_pin_was_sent(
    authed: httpx.AsyncClient, ctx: AppContext, fault: str
) -> None:
    """Final review I3 (a): the PIN went out, then the SIM's state could not be read back. Not a bare error
    that hides the spent try: not accepted, the state unknown, and a message that says the PIN was sent."""
    modem = await _needs_pin(ctx)
    real = modem.answer
    verified: list[str] = []

    def no_read_back(command: str) -> CommandResult | None:
        if VERIFY in command:
            verified.append(command)
        elif verified and ("--uim-get-sim-state" in command or "--get-pin-status" in command):
            if fault == "lost":
                raise TransportError(f"{command}: connection lost")
            return CommandResult(command, "not json\n", "", 0)
        return real(command)

    modem.answer = no_read_back  # type: ignore[method-assign]
    answer = await authed.post(PIN, json={"pin": "9999"})
    assert answer.status_code == 200 and "9999" not in answer.text
    body = answer.json()
    assert (body["accepted"], body["message"]) == (False, SENT_NO_STATE)
    assert (body["sim"]["pin"], body["sim"]["tries_left"], body["sim"]["can_enter_pin"]) == (
        "unknown",
        None,
        False,
    )
    assert len(verified) == 1 and _audited(ctx) == [AUDITED_VERIFY]
    assert modem.pin1_tries == 2  # the try was spent


async def test_the_pin_is_shown_nowhere_but_the_command_sent(
    authed: httpx.AsyncClient, ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    """Review Focus 1: a wrong PIN, then the right one. The audit hides both, and no answer or log record
    holds either; the modem got both."""
    caplog.set_level(logging.DEBUG)
    modem = await _needs_pin(ctx)
    sent = await _sent(ctx)
    wrong = await authed.post(PIN, json={"pin": "9999"})
    right = await authed.post(PIN, json={"pin": "0000"})
    assert (wrong.json()["accepted"], right.json()["accepted"]) == (False, True)
    assert [c for c in sent if VERIFY in c] == [
        "uqmi -s -d /dev/cdc-wdm0 -t 5000 --verify-pin1 9999",
        "uqmi -s -d /dev/cdc-wdm0 -t 5000 --verify-pin1 0000",
    ]
    audited = _audited(ctx)
    assert audited == [AUDITED_VERIFY, AUDITED_VERIFY]
    shown = [*audited, wrong.text, right.text, *(r.getMessage() for r in caplog.records)]
    assert not any(pin in text for text in shown for pin in ("0000", "9999"))
    assert modem.pin1 == "verified"


async def test_a_pin_equal_to_the_timeout_hides_only_the_pin(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """Security L3: the audit hides the PIN by position, so PIN 5000 leaves `-t 5000` as sent; hiding both
    would tell the PIN."""
    await _needs_pin(ctx)
    answer = await authed.post(PIN, json={"pin": "5000"})
    assert answer.status_code == 200 and "5000" not in answer.text
    assert _audited(ctx) == [AUDITED_VERIFY]


@pytest.mark.parametrize(
    ("pin", "detail"),
    [("12ab", "A PIN is 4 to 8 digits"), ("123", "A PIN is 4 to 8 digits"), ("1" * 17, None)],
)
async def test_a_pin_that_breaks_the_rule_is_a_422_that_does_not_echo_it(
    authed: httpx.AsyncClient, ctx: AppContext, pin: str, detail: str | None
) -> None:
    modem = await _needs_pin(ctx)
    sent = await _sent(ctx)
    answer = await authed.post(PIN, json={"pin": pin})
    assert answer.status_code == 422 and pin not in answer.text
    if detail is not None:
        assert answer.json() == {"detail": detail}
    assert not [c for c in sent if VERIFY in c] and _audited(ctx) == []
    assert modem.pin1_tries == 3


@pytest.mark.parametrize(
    ("pin1", "tries", "detail"),
    [
        ("disabled", 3, "The SIM does not ask for a PIN"),
        ("verified", 3, "The SIM does not ask for a PIN"),
        ("not_verified", 1, NOTE_LAST_TRY),  # E3: the app never spends the last try
        ("blocked", 0, NOTE_BLOCKED),
    ],
)
async def test_enter_pin_is_refused_with_nothing_sent(
    authed: httpx.AsyncClient, ctx: AppContext, pin1: str, tries: int, detail: str
) -> None:
    modem = await _modem(ctx)
    modem.pin1, modem.pin1_tries = pin1, tries
    sent = await _sent(ctx)
    answer = await authed.post(PIN, json={"pin": "0000"})
    assert (answer.status_code, answer.json()) == (409, {"detail": detail})
    assert not [c for c in sent if VERIFY in c] and _audited(ctx) == []
    assert (modem.pin1, modem.pin1_tries) == (pin1, tries)


async def test_enter_pin_without_a_tries_count_is_refused_with_nothing_sent(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    """E3 fails closed (security L5, ruling P15): the modem does not say how many tries are left."""
    modem = await _needs_pin(ctx)
    modem.pin1_tries = None  # type: ignore[assignment]
    sent = await _sent(ctx)
    state = (await authed.get(SIM)).json()
    assert (state["pin"], state["tries_left"], state["can_enter_pin"], state["note"]) == (
        "needed",
        None,
        False,
        NOTE_NO_TRIES,
    )
    answer = await authed.post(PIN, json={"pin": "0000"})
    assert (answer.status_code, answer.json()) == (409, {"detail": NOTE_NO_TRIES})
    assert not [c for c in sent if VERIFY in c] and _audited(ctx) == []
    assert modem.pin1 == "not_verified"


async def test_enter_pin_during_a_run_is_a_423_with_nothing_sent(
    authed_guard_live: httpx.AsyncClient, ctx_guard_live: AppContext
) -> None:
    modem = await _needs_pin(ctx_guard_live)
    sent = await _sent(ctx_guard_live)
    answer = await authed_guard_live.post(PIN, json={"pin": "0000"})
    assert answer.status_code == 423 and "0000" not in answer.text
    assert not [c for c in sent if VERIFY in c] and ctx_guard_live.audit.query() == []
    assert (modem.pin1, modem.pin1_tries) == ("not_verified", 3)


async def test_enter_pin_while_another_lte_write_runs_is_a_409(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    modem = await _needs_pin(ctx)
    sent = await _sent(ctx)
    async with ctx.lte.write_slot(ctx.routers.get("ap1")):  # type: ignore[arg-type]
        answer = await authed.post(PIN, json={"pin": "0000"})
    assert (answer.status_code, answer.json()) == (
        409,
        {"detail": "An LTE action is already running on AP1 · bench"},
    )
    assert not [c for c in sent if VERIFY in c] and modem.pin1 == "not_verified"


async def test_enter_pin_while_recover_runs_is_a_409(authed: httpx.AsyncClient, ctx: AppContext) -> None:
    gate = asyncio.Event()

    async def held(_s: float) -> None:  # Recover waits in its Reconnect check until the gate opens
        await gate.wait()

    ctx.lte._sleep = held  # type: ignore[method-assign]
    ctx.lte.poll_s = 1.0
    modem = await _needs_pin(ctx)
    modem.wedged = True
    preview = await ctx.lte_recover.preview("ap1")
    await ctx.lte_recover.start("ap1", preview.digest)
    try:
        sent = await _sent(ctx)
        answer = await authed.post(PIN, json={"pin": "0000"})
        assert (answer.status_code, answer.json()) == (409, {"detail": "LTE recovery runs on AP1 · bench"})
        assert not [c for c in sent if VERIFY in c] and modem.pin1 == "not_verified"
    finally:
        gate.set()
        await ctx.lte_recover.finished("ap1")


async def test_a_lost_connection_that_names_the_command_does_not_show_the_pin(
    authed: httpx.AsyncClient, ctx: AppContext
) -> None:
    modem = await _needs_pin(ctx)
    real = modem.answer

    def lost(command: str) -> CommandResult | None:
        if VERIFY in command:
            raise TransportError(f"{command}: connection lost")
        return real(command)

    modem.answer = lost  # type: ignore[method-assign]
    answer = await authed.post(PIN, json={"pin": "0000"})
    assert answer.status_code == 502 and "0000" not in answer.text
    assert answer.json()["detail"] == f"{AUDITED_VERIFY}: connection lost"
    assert _audited(ctx) == [AUDITED_VERIFY]


async def test_an_unknown_router_is_a_404(authed: httpx.AsyncClient) -> None:
    assert (await authed.get("/api/routers/nope/lte/sim")).status_code == 404
    assert (await authed.post("/api/routers/nope/lte/sim/pin", json={"pin": "0000"})).status_code == 404
