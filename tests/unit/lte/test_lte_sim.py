import json
from pathlib import Path

import pytest

from openwrtgui.lte.sim import SimState, parse_sim_state

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ap2" / "modem_sim.json"


def _recorded(option: str) -> str:
    answers = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for command, answer in answers.items():
        if option in command:
            return str(answer["stdout"])
    raise AssertionError(option)


def test_ap2s_sim_has_its_pin_off_with_three_tries() -> None:
    state = parse_sim_state(_recorded("--uim-get-sim-state"))
    assert state == SimState(
        pin="off", tries_left=3, puk_tries_left=10, card="ready", can_enter_pin=False, note=None
    )


def test_the_pin_status_fallback_reads_unblock_tries() -> None:
    state = parse_sim_state(_recorded("--get-pin-status"))
    assert state is not None
    assert state.puk_tries_left == 10


@pytest.mark.parametrize(
    ("pin1", "card", "tries", "pin", "can"),
    [
        ("not_verified", "pin1_or_upin_pin_required", 3, "needed", True),
        ("not_verified", None, 1, "needed", False),  # E3: never the last try
        ("verified", "ready", 3, "entered", False),
        ("blocked", "puk1_or_upin_puk_required", 0, "blocked", False),
        ("permanently_blocked", None, 0, "blocked", False),
        ("changed", None, 3, "unknown", False),
    ],
)
def test_pin_states(pin1: str, card: str | None, tries: int, pin: str, can: bool) -> None:
    answer: dict[str, str | int] = {
        "pin1_status": pin1,
        "pin1_verify_tries": tries,
        "pin1_unlock_tries": 10,
    }
    if card is not None:
        answer["card_application_state"] = card
    state = parse_sim_state(json.dumps(answer))
    assert state is not None
    assert (state.pin, state.can_enter_pin, state.tries_left) == (pin, can, tries)


def test_notes_are_the_uis_words() -> None:
    blocked = parse_sim_state('{"pin1_status":"blocked","pin1_verify_tries":0}')
    assert blocked is not None
    assert blocked.note == "The SIM is blocked: it needs its PUK, which the app does not offer"
    last = parse_sim_state('{"pin1_status":"not_verified","pin1_verify_tries":1}')
    assert last is not None
    assert last.note == (
        "One try left: enter the PIN in a phone or the D-Link UI, so a wrong PIN does not block the SIM"
    )


def test_pin_needed_with_unknown_tries_can_be_entered() -> None:
    state = parse_sim_state('{"pin1_status":"not_verified"}')
    assert state is not None
    assert state.can_enter_pin is True
    assert state.tries_left is None


@pytest.mark.parametrize("bad", ["", "not json", "[1]", '{"card_slot":1}'])
def test_no_pin_status_is_no_answer(bad: str) -> None:
    assert parse_sim_state(bad) is None
