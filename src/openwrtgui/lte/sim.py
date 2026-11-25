"""The SIM's PIN state as uqmi reports it (--uim-get-sim-state, or --get-pin-status as the fallback)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

PinState = Literal["off", "needed", "entered", "blocked", "unknown"]

_MIN_TRIES_TO_ENTER = 2  # E3: the app never spends the last try
_PIN_BY_STATUS: dict[str, PinState] = {
    "disabled": "off",
    "not_verified": "needed",
    "verified": "entered",
    "blocked": "blocked",
    "permanently_blocked": "blocked",
}
NOTE_BLOCKED = "The SIM is blocked: it needs its PUK, which the app does not offer"
NOTE_LAST_TRY = (
    "One try left: enter the PIN in a phone or the D-Link UI, so a wrong PIN does not block the SIM"
)
NOTE_NO_TRIES = (
    "The modem did not say how many tries are left: enter the PIN in a phone or the D-Link UI, "
    "so a wrong PIN does not block the SIM"
)


@dataclass(frozen=True)
class SimState:
    pin: PinState
    tries_left: int | None
    puk_tries_left: int | None
    card: str | None
    can_enter_pin: bool
    note: str | None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_sim_state(text: str) -> SimState | None:
    """None: the answer is not a JSON object or has no pin1_status."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pin1_status"), str):
        return None
    pin = _PIN_BY_STATUS.get(data["pin1_status"], "unknown")
    tries = _int(data.get("pin1_verify_tries"))
    puk = _int(data.get("pin1_unlock_tries"))
    if puk is None:  # --get-pin-status spells it "unblock"
        puk = _int(data.get("pin1_unblock_tries"))
    card = data.get("card_application_state")
    needed = pin == "needed"
    # E3 fails closed (security L5, ruling P15): with no tries count the next try may be the last
    can_enter = needed and tries is not None and tries >= _MIN_TRIES_TO_ENTER
    note = None
    if pin == "blocked":
        note = NOTE_BLOCKED
    elif needed and tries is None:
        note = NOTE_NO_TRIES
    elif needed and not can_enter:
        note = NOTE_LAST_TRY
    return SimState(
        pin=pin,
        tries_left=tries,
        puk_tries_left=puk,
        card=card if isinstance(card, str) else None,
        can_enter_pin=can_enter,
        note=note,
    )
